"""Order Management System state machine (scaffold).

Satisfies the infra-audit requirements:
  * Never assume instant fills — orders move through explicit states driven by
    broker ack/fill/partial events, not optimistic assumptions.
  * Partial fills tracked (filled_qty vs order_qty); the remainder stays working.
  * Cancel/replace on a timeout if the market moves away from a limit price.

Transport-agnostic: feed it broker events via `on_event`; drive order actions
through the injected `broker` adapter (submit/cancel/replace). No broker here.
"""
from __future__ import annotations

import asyncio
import enum
import time
import uuid
from dataclasses import dataclass, field


class OrderState(enum.Enum):
    NEW = "new"
    PENDING = "pending"       # submitted, awaiting ack
    WORKING = "working"       # acked, resting/partially filled
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"


@dataclass
class Order:
    symbol: str
    side: str                 # 'buy' | 'sell'
    limit_price: float
    order_qty: int
    client_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    broker_id: str | None = None
    state: OrderState = OrderState.NEW
    filled_qty: int = 0
    avg_fill_price: float = 0.0
    created: float = field(default_factory=time.monotonic)

    @property
    def remaining(self) -> int:
        return max(self.order_qty - self.filled_qty, 0)


class OMS:
    """Order lifecycle manager with partial-fill + cancel/replace handling."""

    def __init__(self, broker, *, reprice_timeout_s: float = 3.0):
        self.broker = broker            # adapter: submit(order)/cancel(id)/replace(id,px)
        self.reprice_timeout_s = reprice_timeout_s
        self.orders: dict[str, Order] = {}

    async def submit(self, order: Order) -> Order:
        self.orders[order.client_id] = order
        order.state = OrderState.PENDING
        order.broker_id = await self.broker.submit(order)  # returns broker id
        return order

    def on_event(self, ev: dict) -> None:
        """Broker execution event: {client_id, type, filled_qty, price, ...}."""
        o = self.orders.get(ev.get("client_id"))
        if not o:
            return
        etype = ev.get("type")
        if etype == "ack":
            o.state = OrderState.WORKING
        elif etype in ("fill", "partial"):
            fq = int(ev.get("filled_qty", 0))
            px = float(ev.get("price", o.limit_price))
            # Weighted-average fill price across partials.
            total = o.avg_fill_price * o.filled_qty + px * fq
            o.filled_qty = min(o.filled_qty + fq, o.order_qty)
            o.avg_fill_price = total / o.filled_qty if o.filled_qty else px
            o.state = OrderState.FILLED if o.remaining == 0 else OrderState.PARTIAL
        elif etype == "canceled":
            o.state = OrderState.CANCELED
        elif etype == "rejected":
            o.state = OrderState.REJECTED

    async def manage_working_orders(self, market_px_for) -> None:
        """Cancel/replace resting orders that have aged past the reprice timeout
        while the market has moved away from the limit. Call periodically."""
        now = time.monotonic()
        for o in list(self.orders.values()):
            if o.state not in (OrderState.WORKING, OrderState.PARTIAL):
                continue
            if now - o.created < self.reprice_timeout_s:
                continue
            mkt = market_px_for(o.symbol, o.side)  # current bid (sell) / ask (buy)
            if mkt is None or abs(mkt - o.limit_price) < 1e-9:
                continue
            # Reprice the REMAINDER to the current touch; broker handles the swap.
            new_id = await self.broker.replace(o.broker_id, mkt)
            o.broker_id = new_id
            o.limit_price = mkt
            o.created = now

    def open_orders(self) -> list[Order]:
        return [o for o in self.orders.values()
                if o.state in (OrderState.WORKING, OrderState.PARTIAL,
                               OrderState.PENDING)]
