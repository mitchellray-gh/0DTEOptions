"""Crash-recovery state reconciliation (scaffold).

Satisfies the infra-audit requirement: on boot, the system must reconcile its
LOCAL view against the BROKER's actual open orders and positions before taking
any action. The broker is the source of truth; local intent is mirrored in Redis
(never a browser / localStorage).
"""
from __future__ import annotations

import logging

log = logging.getLogger("exec.recovery")


async def reconcile(broker, store) -> dict:
    """Compare local (Redis) intent to broker reality; return a reconciliation
    report and correct the local store. Never trades here — a human/strategy
    decides what to do with the discrepancies.

    broker:  adapter with async open_orders() / positions()
    store:   async get_local_orders() / get_local_positions() / set_*()
    """
    broker_orders = {o["broker_id"]: o for o in await broker.open_orders()}
    broker_pos = {p["symbol"]: p for p in await broker.positions()}
    local_orders = await store.get_local_orders()
    local_pos = await store.get_local_positions()

    # Orders the broker has but we lost track of (orphans).
    orphan_orders = [o for bid, o in broker_orders.items()
                     if bid not in {lo.get("broker_id") for lo in local_orders}]
    # Orders we think are open but the broker doesn't (stale local state).
    stale_orders = [lo for lo in local_orders
                    if lo.get("broker_id") not in broker_orders]
    # Position mismatches.
    pos_mismatch = []
    for sym, bp in broker_pos.items():
        lp = local_pos.get(sym)
        if not lp or int(lp.get("qty", 0)) != int(bp.get("qty", 0)):
            pos_mismatch.append({"symbol": sym, "broker": bp, "local": lp})

    # Correct local store to match the broker (source of truth).
    await store.set_local_orders(list(broker_orders.values()))
    await store.set_local_positions(list(broker_pos.values()))

    report = {
        "orphan_orders": orphan_orders,
        "stale_orders": stale_orders,
        "position_mismatches": pos_mismatch,
        "clean": not (orphan_orders or stale_orders or pos_mismatch),
    }
    if not report["clean"]:
        log.warning("state reconciliation found discrepancies: %s", report)
    return report
