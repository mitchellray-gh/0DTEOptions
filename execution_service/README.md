# Execution Service (scaffold — NOT production, NOT wired to the app)

This is a **separate, decoupled** live-execution microservice scaffold, created in
response to the infrastructure audit. It is intentionally **not imported by the
educational web app** (`backend/`, `frontend/`) and shares no state with it.

## Why it's separate

The audits concluded the research app **must not** be pointed at a live brokerage:
the app is a delayed-data, REST-polling, browser-localStorage research/education
tool with no order path. A real 0DTE options execution engine is a streaming,
stateful, fault-tolerant service — this folder is the skeleton of that engine.

## Status: SCAFFOLD ONLY

- No real broker adapter is included (needs Alpaca/IBKR/Tradier creds + a signed
  market-data agreement).
- **Paper-first**: any adapter must be validated in paper mode for weeks before
  a single real order.
- The strategy it would run (late-session 0DTE premium selling) has **not** passed
  the quant audit yet — see `backend/strategy_c_backtest.py` for the honest,
  bid/ask-filled, out-of-sample result. Do not deploy a strategy that fails OOS.

## Components (each maps to an infra-audit requirement)

| File | Audit requirement it satisfies |
|------|-------------------------------|
| `stream.py`    | Persistent WebSocket + exponential backoff + heartbeat; async non-blocking ingest |
| `ratelimit.py` | Token bucket + jittered backoff on HTTP 429/418; local Greeks (no per-contract REST) |
| `oms.py`       | Order state machine: submit → ack → partial-fill tracking → cancel/replace on timeout |
| `recovery.py`  | On boot, reconcile local state against the broker's actual open orders/positions |
| `watchdog.py`  | Server-side risk holder: dead-man's-switch flattens on feed loss + flatten-by-15:55 |

## Hard rules baked into the design

1. **Never assume instant fills** — act only on ack/fill/partial events.
2. **Never iterate the chain via per-contract REST** — subscribe by underlying,
   compute Greeks locally.
3. **State of record is the broker**, mirrored in Redis — never a browser.
4. **The watchdog can flatten independently** of any UI, and *will* on data loss.
