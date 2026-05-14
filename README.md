# 0DTE Options Scanner

> **Find undervalued zero-days-to-expiration (0DTE) options and get explicit, broker-ready trade instructions — all in a lite local web app.**

Liquid US-listed underlyings (SPY, QQQ, IWM, DIA, …) now have option contracts that expire **today**. Their premiums move violently against time decay (theta) and tiny shifts in implied volatility, which means the bid/ask is occasionally mispriced relative to the rest of the chain. This tool finds those mispricings and tells you exactly what to do about them.

> ⚠️ **Educational use only.** 0DTE options can lose 100% of premium in minutes. Always verify quotes in your broker before trading.

---

## How it works

1. **Fetch** — for each ticker, pull the 0DTE option chain (or the nearest expiry within 3 days) from Yahoo Finance via [`yfinance`](https://github.com/ranaroussi/yfinance).
2. **Anchor** — compute a chain-wide **reference IV** as the volume-weighted IV of liquid, near-the-money contracts. This is the market's own consensus for *today*'s realized vol.
3. **Reprice** — for every contract, compute the Black-Scholes fair value at the reference IV and compare it to the live ask.
4. **Filter** — drop anything with thin liquidity, wide spreads, or less than a 5% edge.
5. **Rank** — composite score blends edge %, liquidity, and ATM-ness.
6. **Plan** — for each surviving contract, build a trade plan: position size (risk-budgeted), limit price, breakeven, take-profit, stop-loss, and a numbered execution checklist.

A small **React + Vite** UI consumes the FastAPI backend, lets you tune filters, and shows the trade plan side-by-side with a sortable table of opportunities.

---

## Architecture

```
┌────────────────────────────┐    HTTP /api    ┌──────────────────────┐
│  React UI (Vite, port 5173)│ ──────────────► │ FastAPI (port 8000)  │
│  src/App.jsx               │                 │ backend/main.py      │
│  src/components/...        │                 │   ├ scanner.py       │
│                            │                 │   ├ pricing.py (BS)  │
│                            │                 │   └ models.py        │
└────────────────────────────┘                 └──────────┬───────────┘
                                                          │
                                                          ▼
                                                  yfinance → Yahoo
```

---

## Quick start

### 1. Backend

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000
```

The API exposes:

- `GET /api/health`
- `GET /api/opportunities?tickers=SPY,QQQ&account_size=5000&risk_per_trade_pct=0.02&max_results=50`

Responses are cached for 30 seconds. Append `&nocache=true` to bypass.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. The Vite dev server proxies `/api/*` to the backend.

For a static build:

```bash
npm run build      # output in frontend/dist/
npm run preview    # serve the build on :4173
```

---

## API response shape

```jsonc
{
  "generated_at": "2026-05-14T14:30:00Z",
  "risk_free_rate": 0.045,
  "tickers_scanned": ["SPY", "QQQ"],
  "count": 7,
  "results": [
    {
      "opportunity": {
        "symbol": "SPY260514C00525000",
        "underlying": "SPY",
        "strike": 525.0,
        "option_type": "call",
        "bid": 0.42, "ask": 0.45, "mid": 0.435,
        "fair_value": 0.58,
        "edge_pct": 0.288,
        "delta": 0.41,
        "minutes_to_expiry": 95,
        "score": 31.4
      },
      "plan": {
        "action": "BUY_TO_OPEN",
        "side_human": "BUY 2 SPY 2026-05-14 $525 CALL",
        "limit_price": 0.45,
        "suggested_contracts": 2,
        "total_cost_usd": 90.0,
        "max_loss_usd": 90.0,
        "breakeven_underlying_price": 525.45,
        "target_exit_price": 0.52,
        "target_profit_usd": 14.0,
        "stop_loss_price": 0.23,
        "stop_loss_usd": 44.0,
        "rationale": "Black-Scholes fair value …",
        "steps": ["1. In your broker …", "2. Select the …", "…"]
      }
    }
  ],
  "notes": ["SPY: spot=$524.80, expiry=2026-05-14, ref_IV=14.3%, mins_left=95"]
}
```

---

## Configuration knobs

All exposed both as query parameters and as UI form fields:

| Parameter | Default | Description |
|---|---|---|
| `tickers` | `SPY,QQQ,IWM,DIA,SPX,NDX` | Comma-separated underlyings to scan |
| `account_size` | `5000` (USD) | Used to size positions |
| `risk_per_trade_pct` | `0.02` | Max fraction of account to risk per contract |
| `max_results` | `50` | Cap on returned opportunities |
| `risk_free_rate` | `0.045` | Annualized risk-free rate for BS pricing |

Internal liquidity filters (in `backend/scanner.py`) — tune to taste:

- `MIN_VOLUME = 50`
- `MIN_OPEN_INTEREST = 100`
- `MIN_BID = 0.05`
- `MAX_REL_SPREAD = 0.25`
- Minimum edge: 5%

---

## Project layout

```
.
├── backend/
│   ├── __init__.py
│   ├── main.py        ← FastAPI app + CORS + 30s cache
│   ├── scanner.py     ← chain fetch, reference-IV calc, edge ranking, trade plan
│   ├── pricing.py     ← Black-Scholes price, IV (Brent), Greeks
│   └── models.py      ← Pydantic schemas (Opportunity, TradePlan, ScanResponse)
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   └── src/
│       ├── main.jsx
│       ├── App.jsx
│       ├── api.js
│       ├── styles.css
│       └── components/
│           ├── OpportunityTable.jsx
│           └── TradeDetail.jsx
├── requirements.txt
└── README.md
```

---

## Caveats

- **Yahoo data is delayed** (~15 min for some venues). For live trading, swap `yfinance` for a real-time options feed (Polygon.io, Tradier, IBKR, CBOE) — the swap is contained to `_build_chain_context()` in `backend/scanner.py`.
- **Black-Scholes for American options** — SPY/QQQ etc. weeklies are American. For 0DTE near-the-money calls/puts on non-dividend names the difference is negligible; for deep-ITM puts and dividend-heavy names you may want a binomial tree.
- **The "fair value" is a relative anchor**, not an absolute truth. We measure deviations *from the rest of the same chain*, which catches stale quotes and momentary dislocations — not directional alpha.
- **No order routing.** This tool deliberately stops at "tell me the trade." Sending orders is your responsibility (and your broker's).
