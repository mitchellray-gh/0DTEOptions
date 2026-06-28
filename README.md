# 0DTE Options Scanner

> **Find undervalued zero-days-to-expiration (0DTE) options and get explicit, broker-ready trade instructions — all in a lite local web app.**

Liquid US-listed underlyings (SPY, QQQ, IWM, DIA, …) now have option contracts that expire **today**. Their premiums move violently against time decay (theta) and tiny shifts in implied volatility, which means the bid/ask is occasionally mispriced relative to the rest of the chain. This tool finds those mispricings and tells you exactly what to do about them.

> ⚠️ **Educational use only.** 0DTE options can lose 100% of premium in minutes. Always verify quotes in your broker before trading.

---

## How it works

1. **Fetch** — for each ticker, the Python backend pulls the 0DTE option chain (or the nearest expiry within 3 days) from Yahoo Finance via [`yfinance`](https://github.com/ranaroussi/yfinance). This is the **only** thing the backend does — a browser can't call Yahoo directly because of CORS.
2. **Anchor** — *(in the browser)* compute a chain-wide **reference IV** as the volume-weighted IV of liquid, near-the-money contracts. This is the market's own consensus for *today*'s realized vol.
3. **Reprice** — *(in the browser)* for every contract, compute the Black-Scholes fair value at the reference IV and compare it to the live ask.
4. **Filter** — drop anything with thin liquidity, wide spreads, or less than a 5% edge.
5. **Rank** — composite score blends edge %, liquidity, and ATM-ness.
6. **Plan** — for each surviving contract, build a trade plan: position size (risk-budgeted), limit price, breakeven, take-profit, stop-loss, and a numbered execution checklist.

Steps 2–6 run **entirely in React** (`frontend/src/lib/pricing.js` + `scanner.js`),
a faithful port of the Python engine — verified to match it numerically. Because
scoring is client-side, changing your account size or risk re-scores instantly
with no refetch. The same logic stays in Python (`backend/scanner.py`,
`pricing.py`) to power the [backtester](#backtesting).

---

## Architecture

```
┌─────────────────────────────────────┐   GET /api/chain   ┌─────────────────────┐
│  React UI (Vite, port 5173)         │ ─────────────────► │ FastAPI (port 8000) │
│   src/App.jsx — watchlist + scan    │   (raw chain only) │ backend/main.py     │
│   src/lib/pricing.js  (Black-Scholes)│ ◄───────────────── │  └ scanner.fetch_   │
│   src/lib/scanner.js  (edge + plan) │    JSON chains     │     chains()        │
│   src/components/...                │                    └──────────┬──────────┘
└─────────────────────────────────────┘                               │
        ▲ all pricing + scoring here                                  ▼
        └──────────── (no math on the server) ──────────────  yfinance → Yahoo
```

The backend is a **thin data proxy**. All the math lives in the React app.

---

## Quick start

### 1. Backend (data proxy)

```bash
pip install -r requirements-dev.txt
uvicorn backend.main:app --reload --port 8000
```

The API exposes:

- `GET /api/health`
- `GET /api/chain?tickers=SPY,QQQ` — **raw** option chains (all the web app needs; it scores them client-side). Cached ~20s; append `&nocache=true` to bypass.
- `POST /api/backtest` — see [Backtesting](#backtesting).

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

The UI opens on a **watchlist** of tickers (saved in your browser via
`localStorage`). Type a symbol (e.g. `AAPL`) and click **Add** to track it, remove
one with the ×, then hit **Scan watchlist** to pull live opportunities for exactly
those names. Account size, risk-per-trade, minimum edge, and call/put filters are
right below the watchlist.

---

## Deploy to Vercel

The repo is configured to deploy as a single Vercel project: the React build is
served as static files and the FastAPI backend runs as a Python serverless
function (`api/index.py`), wired together by [`vercel.json`](vercel.json).

```bash
npm i -g vercel      # one-time
vercel               # preview deploy (prompts you to log in + link the project)
vercel --prod        # production deploy
```

No environment variables are required — the frontend calls `/api/*` on the same
origin, which `vercel.json` rewrites to the serverless function. To point the UI
at a different backend instead, set `VITE_API_BASE` (e.g.
`https://my-backend.example.com`) as a build-time env var in the Vercel project.

To keep the serverless bundle within Vercel's size limit, the Black-Scholes engine
uses Python's standard-library `math.erfc` for the normal CDF instead of SciPy, so
**SciPy is no longer a dependency**.

> **Heads-up on live data.** The scanner pulls quotes from Yahoo via `yfinance`.
> Yahoo frequently rate-limits or blocks requests from datacenter IPs (which is
> what serverless functions use), so a deployed scan may intermittently return no
> results. Each function invocation is also capped at 60s — scan a focused
> watchlist, not the whole S&P 500. For reliable data, run the backend somewhere
> with a residential/commercial IP (or swap in a paid options feed — see
> [Caveats](#caveats)) and point the Vercel frontend at it via `VITE_API_BASE`.

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

## Backtesting

A backtesting module lives in `backend/backtest/`. It runs the **exact same**
strategy code the live API uses — the reference-IV anchor
(`compute_reference_iv`), the per-contract scoring (`_evaluate_contract`), and
the position sizing / take-profit / stop-loss rules (`_build_plan`) are all
imported from `backend/scanner.py` — then settles each trade and reports
performance.

```bash
# Offline, deterministic Monte-Carlo run (no network):
python -m backend.backtest --source gbm --days 250 --seed 7

# Drive the simulation off real historical SPY/QQQ daily bars:
python -m backend.backtest --source yfinance --tickers SPY,QQQ --days 90

# Settle real recorded live scans against actual settlement (see below):
python -m backend.backtest replay --snapshots snapshots/

# Dump the full result (trades, equity curve, metrics) to JSON:
python -m backend.backtest --days 250 --json result.json
```

Or hit it over HTTP — `POST /api/backtest` with a JSON body like
`{ "source": "gbm", "days": 120, "mean_reversion": 0.7 }`. It reports win rate,
profit factor, expectancy, max drawdown, an annualized Sharpe, an equity curve,
and a breakdown of exits by reason (take-profit / stop-loss / expiry) and by
option type.

### Profit metrics: aligned & assigned

Every trade carries the **assigned** targets straight from the live trade plan
(`planned_target_usd` = `plan.target_profit_usd`, `planned_max_loss_usd` =
`plan.max_loss_usd`, plus the resulting `planned_rr` reward:risk and the
realized `target_capture_pct`). The aggregate metrics add `total_planned_profit`,
`total_planned_max_loss`, `plan_capture_ratio` (realized net ÷ assigned target)
and `avg_planned_rr`, so you can see how the realized result lines up against
what the plan promised.

Each trade's realized gross P&L is also **assigned to its drivers** via a
Black-Scholes repricing waterfall that reconciles exactly:

```
underlying move  +  vol reversion  +  time decay  +  execution/fill  =  gross P&L
gross P&L        +  commission                                       =  net P&L
```

`metrics.pnl_attribution` rolls these up across all trades. This makes the
strategy's structure explicit — e.g. a typical run shows the underlying move is
*positive*, but the trade plan's small take-profit vs. large stop-loss (an
assigned reward:risk near `0.12 : 1`) bleeds it all back through the execution
bucket.

### How the two modes work

- **`gbm` / `yfinance` (simulation)** — for each trading day the engine builds a
  synthetic 0DTE chain around the day's open. Each contract is priced with
  Black-Scholes at a per-contract IV of `base_iv × (1 + smile) + noise`; that
  noise is what makes some contracts look cheap to the scanner. Trades are then
  walked through the day along an intraday price path (a real GBM path, or a
  Brownian bridge reconstructed from the real OHLC bar) and exited on
  take-profit, stop-loss, or expiry. The modeled alpha is **mispricing
  reversion**: with probability `reversion_prob`, a cheap quote drifts back
  toward the chain's reference IV by a fraction `mean_reversion`. Set
  `--mean-reversion 0` to see how the strategy does on the underlying move alone.
- **`replay` (real data)** — because free historical *intraday* option quotes
  don't exist, you collect live scans over time and settle them later. In the
  web UI, scan your watchlist and click **Export snapshot** to download a
  `snapshot-<timestamp>.json` into a `snapshots/` folder; once those contracts
  expire, `replay` fetches each underlying's actual settlement close and books
  the trade at intrinsic value (hold-to-expiry).

> ⚠️ The simulation is a **stress-test of the strategy's logic**, not a replay
> of real option quotes — its P&L is driven by the reversion assumption you set.
> Treat the numbers as a way to reason about the strategy's structure (e.g. the
> trade plan's small take-profit vs. large stop-loss), not as a track record.

Run the backtester's test suite (stdlib `unittest`, no extra dependencies):

```bash
python -m unittest discover -s backend/backtest/tests
```

---

## Project layout

```
.
├── backend/
│   ├── __init__.py
│   ├── main.py        ← FastAPI app + CORS + cache + /api/backtest
│   ├── scanner.py     ← chain fetch, reference-IV calc, edge ranking, trade plan
│   ├── pricing.py     ← Black-Scholes price, IV (Brent), Greeks
│   ├── models.py      ← Pydantic schemas (Opportunity, TradePlan, ScanResponse)
│   ├── sp500.py       ← S&P 500 constituent list (Wikipedia + fallback)
│   └── backtest/      ← strategy backtester (simulation + replay)
│       ├── engine.py      ← orchestration: simulate → score → settle → metrics
│       ├── simulator.py   ← synthetic chains + GBM / OHLC price paths
│       ├── settlement.py  ← per-trade P&L (take-profit / stop-loss / expiry)
│       ├── metrics.py     ← win rate, profit factor, drawdown, Sharpe …
│       ├── replay.py      ← settle recorded live scans vs. real settlement
│       ├── models.py      ← BacktestConfig / BacktestResult
│       ├── cli.py         ← `python -m backend.backtest`
│       └── tests/         ← unittest suite
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   └── src/
│       ├── main.jsx
│       ├── App.jsx       ← watchlist UI + runs the scan in-browser
│       ├── api.js        ← fetches raw chains from /api/chain
│       ├── styles.css
│       ├── lib/
│       │   ├── pricing.js  ← Black-Scholes / IV / Greeks (JS port)
│       │   └── scanner.js  ← reference-IV, edge ranking, trade plan (JS port)
│       └── components/
│           ├── OpportunityTable.jsx
│           ├── TradeDetail.jsx
│           └── RejectionInsights.jsx
├── api/
│   └── index.py       ← Vercel serverless entry (exposes backend.main:app)
├── vercel.json        ← Vercel build + /api rewrite + 60s function config
├── requirements.txt   ← runtime deps bundled into the Vercel function
├── requirements-dev.txt ← local-dev extras (uvicorn, lxml)
└── README.md
```

---

## Caveats

- **Yahoo data is delayed** (~15 min for some venues). For live trading, swap `yfinance` for a real-time options feed (Polygon.io, Tradier, IBKR, CBOE) — the swap is contained to `_build_chain_context()` in `backend/scanner.py`.
- **Black-Scholes for American options** — SPY/QQQ etc. weeklies are American. For 0DTE near-the-money calls/puts on non-dividend names the difference is negligible; for deep-ITM puts and dividend-heavy names you may want a binomial tree.
- **The "fair value" is a relative anchor**, not an absolute truth. We measure deviations *from the rest of the same chain*, which catches stale quotes and momentary dislocations — not directional alpha.
- **No order routing.** This tool deliberately stops at "tell me the trade." Sending orders is your responsibility (and your broker's).
