"""Turn a scanner trade plan into a Robinhood-MCP-ready order.

The scanner stops at *"here is the exact trade"*. This module bridges that last
mile to **execution** by translating an ``(opportunity, plan)`` pair into an
order that can be placed through Robinhood's hosted trading MCP server at
``https://agent.robinhood.com/mcp/trading``.

That endpoint is a remote `Model Context Protocol <https://modelcontextprotocol.io>`_
server: an MCP-capable agent (Claude, the Robinhood agent app, etc.) connects to
it — authenticating with the user's own Robinhood account — and the server
exposes trading *tools* the agent can call on the user's behalf. Because the
server is driven by natural language, the most robust, forward-compatible
interface is a precise instruction string the agent executes. We also emit a
normalised, structured order spec for callers that prefer to map fields onto the
server's tool arguments directly (confirm names against the live ``tools/list``).

Nothing here talks to Robinhood or places an order. It only *prepares* the
instruction; a human (or an explicitly authorised agent) still reviews and
submits it. This keeps the tool's "you are responsible for sending orders"
guarantee intact.
"""
from __future__ import annotations

from typing import Any, Mapping

ROBINHOOD_MCP_ENDPOINT = "https://agent.robinhood.com/mcp/trading"


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a dict or a pydantic/attr object uniformly."""
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _round(value: Any, ndigits: int = 2) -> float:
    try:
        return round(float(value), ndigits)
    except (TypeError, ValueError):
        return 0.0


def _strike_text(strike: Any) -> str:
    """Format a strike like ``525`` or ``525.5`` (drop trailing zeros)."""
    try:
        f = float(strike)
    except (TypeError, ValueError):
        return str(strike)
    return f"{f:g}"


def build_robinhood_order(
    opportunity: Any,
    plan: Any,
    *,
    time_in_force: str = "day",
) -> dict:
    """Build a Robinhood-MCP order from an ``(opportunity, plan)`` pair.

    Parameters
    ----------
    opportunity, plan
        Either the pydantic models (:class:`~backend.models.Opportunity` /
        :class:`~backend.models.TradePlan`) or the plain ``dict`` form the API
        returns. Both are accepted.
    time_in_force
        Order duration. 0DTE contracts expire today, so ``"day"`` is the safe
        default — a ``gtc`` (good-til-cancelled) order would be meaningless.

    Returns
    -------
    dict
        ``endpoint``, a natural-language ``instruction`` for the MCP agent, the
        normalised ``entry`` order, the staged ``exit`` orders (take-profit +
        stop-loss), and a ``disclaimer``.
    """
    underlying = _get(opportunity, "underlying", "")
    option_symbol = _get(opportunity, "symbol", _get(plan, "contract_symbol", ""))
    option_type = str(_get(opportunity, "option_type", "")).lower()
    expiration = _get(opportunity, "expiration", "")
    strike = _get(opportunity, "strike", 0.0)
    minutes_to_expiry = _get(opportunity, "minutes_to_expiry", None)

    quantity = int(_get(plan, "suggested_contracts", 1) or 1)
    limit_price = _round(_get(plan, "limit_price", _get(opportunity, "ask", 0.0)))
    total_cost = _round(_get(plan, "total_cost_usd", 0.0))
    max_loss = _round(_get(plan, "max_loss_usd", 0.0))
    target_exit = _round(_get(plan, "target_exit_price", 0.0))
    target_profit = _round(_get(plan, "target_profit_usd", 0.0))
    stop_price = _round(_get(plan, "stop_loss_price", 0.0))

    tif = str(time_in_force or "day").lower()
    strike_txt = _strike_text(strike)
    type_word = option_type.upper() or "OPTION"
    contract_human = (
        f"{underlying} {expiration} ${strike_txt} {type_word}".strip()
    )

    entry = {
        "underlying_symbol": underlying,
        "option_symbol": option_symbol,
        "expiration_date": expiration,
        "strike_price": _round(strike, 4),
        "option_type": option_type,
        "side": "buy",
        "position_effect": "open",
        "order_type": "limit",
        "limit_price": limit_price,
        "quantity": quantity,
        "time_in_force": tif,
    }

    take_profit = {
        **entry,
        "side": "sell",
        "position_effect": "close",
        "limit_price": target_exit,
        "note": (
            f"Take-profit: sell to close {quantity} contract(s) at "
            f"${target_exit:.2f} (≈ ${target_profit:.2f} profit)."
        ),
    }
    stop_loss = {
        **entry,
        "side": "sell",
        "position_effect": "close",
        "order_type": "stop",
        "stop_price": stop_price,
        "limit_price": None,
        "note": (
            f"Stop-loss: sell to close if the contract trades down to "
            f"${stop_price:.2f} (≈50% of premium)."
        ),
    }

    minutes_clause = (
        f" Only ~{minutes_to_expiry} minutes remain until expiry, so act promptly."
        if isinstance(minutes_to_expiry, (int, float)) and minutes_to_expiry
        else ""
    )

    instruction = (
        f"Using the Robinhood trading MCP server ({ROBINHOOD_MCP_ENDPOINT}), "
        f"place a BUY-TO-OPEN limit order: buy {quantity} contract(s) of the "
        f"{contract_human} option ({option_symbol}) at a limit price of "
        f"${limit_price:.2f} per share, time-in-force {tif.upper()}. "
        f"This costs about ${total_cost:.2f} total and risks at most "
        f"${max_loss:.2f}. After the buy fills, place a SELL-TO-CLOSE limit "
        f"order for the same {quantity} contract(s) at ${target_exit:.2f} "
        f"(take-profit), and sell to close if the contract falls to "
        f"${stop_price:.2f} (stop-loss). Close any remaining position by "
        f"15:45 ET to avoid pin/assignment risk.{minutes_clause} "
        f"Show me the order details and ask for confirmation before submitting."
    )

    return {
        "endpoint": ROBINHOOD_MCP_ENDPOINT,
        "instruction": instruction,
        "entry": entry,
        "exit": [take_profit, stop_loss],
        "disclaimer": (
            "Educational use only. This prepares an order for Robinhood's "
            "trading MCP server but does not place it. Review every detail and "
            "confirm in your account before submitting. 0DTE options can lose "
            "100% of premium in minutes."
        ),
    }
