"""Backtest the credit-spread strategy over simulated 0DTE days and report the
win rate + net P&L. Proves whether defined-risk premium selling clears the
80%-win goal the long-option scanner could not.

Run: python -m backend.spread_backtest [--source gbm|yfinance] [--days N] ...
"""
from __future__ import annotations

import argparse

import numpy as np

from backend import spreads
from backend.pricing import bs_price
from backend.backtest.models import BacktestConfig
from backend.backtest.simulator import iter_days
from backend.backtest.engine import _draw_reversion  # unused but keeps parity


def _rich_chain(spot: float, minutes: int, base_iv: float, rng, *,
                strike_step: float = 1.0, n_each_side: int = 25,
                smile_coef: float = 3.0, iv_noise: float = 0.02,
                r: float = 0.045):
    """A realistic 0DTE chain: many $1-ish OTM strikes with penny quotes.

    Unlike the long-option simulator (which drops sub-$0.02 strikes and uses
    coarse $5 increments), real SPY/SPX 0DTE chains quote far-OTM strikes down
    to a penny — exactly what credit spreads need. This isolates the spread
    test from the long-option chain's granularity quirks.
    """
    T = max(minutes, 1) / (60 * 24 * 365)
    atm = round(spot / strike_step) * strike_step
    calls, puts = [], []
    for i in range(-n_each_side, n_each_side + 1):
        K = round(atm + i * strike_step, 2)
        if K <= 0:
            continue
        moneyness = (K - spot) / spot
        for otype, rows in (("call", calls), ("put", puts)):
            iv = max(0.02, base_iv * (1 + smile_coef * moneyness * moneyness)
                     + float(rng.normal(0, iv_noise)))
            mid = bs_price(spot, K, T, r, iv, otype)
            if mid < 0.01:
                continue
            half = max(mid * 0.03, 0.01)
            rows.append({
                "contractSymbol": f"{otype[0].upper()}{K}",
                "strike": float(K),
                "bid": round(max(mid - half, 0.0), 2),
                "ask": round(mid + half, 2),
                "lastPrice": round(mid, 2),
                "volume": 500.0,
                "openInterest": 2000.0,
                "impliedVolatility": iv,
            })
    return calls, puts


def _chain_rows(df):
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "contractSymbol": str(r.get("contractSymbol", "")),
            "strike": float(r.get("strike") or 0.0),
            "bid": float(r.get("bid") or 0.0),
            "ask": float(r.get("ask") or 0.0),
            "lastPrice": float(r.get("lastPrice") or 0.0),
            "volume": float(r.get("volume") or 0.0),
            "openInterest": float(r.get("openInterest") or 0.0),
            "impliedVolatility": float(r.get("impliedVolatility") or 0.0),
        })
    return rows


def run(cfg: BacktestConfig, *, min_pop: float, max_width: float,
        profit_target: float, stop_multiple: float, max_per_day: int):
    rng = np.random.default_rng(cfg.seed)
    minutes = cfg.session_minutes
    trades = []
    for day in iter_days(cfg, rng):
        if day.calls.empty and day.puts.empty:
            continue
        # Build a rich, finely-striked chain around the day's real open spot.
        calls, puts = _rich_chain(float(day.spot), minutes, cfg.base_iv, rng)
        found = spreads.build_credit_spreads(
            calls, puts, float(day.spot), minutes,
            underlying=day.underlying, expiration=day.expiry_iso,
            risk_free=cfg.risk_free_rate,
            account_size=cfg.account_size,
            risk_per_trade_pct=cfg.risk_per_trade_pct,
            max_width=max_width, min_pop=min_pop, max_results=max_per_day,
        )
        for sp in found[:max_per_day]:
            tr = spreads.settle_spread(
                sp, day.path, date=day.date, risk_free=cfg.risk_free_rate,
                profit_target_frac=profit_target, stop_multiple=stop_multiple,
                commission_per_contract=cfg.commission_per_contract,
            )
            trades.append(tr)
    return trades


def summarize(trades):
    n = len(trades)
    if not n:
        return {"trades": 0}
    wins = [t for t in trades if t.pnl_usd > 0]
    losses = [t for t in trades if t.pnl_usd < 0]
    net = sum(t.pnl_usd for t in trades)
    gw = sum(t.pnl_usd for t in wins)
    gl = abs(sum(t.pnl_usd for t in losses))
    reasons = {}
    for t in trades:
        reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
    return {
        "trades": n,
        "win_rate": len(wins) / n,
        "net": net,
        "expectancy": net / n,
        "profit_factor": (gw / gl) if gl else float("inf"),
        "avg_win": (gw / len(wins)) if wins else 0.0,
        "avg_loss": (gl / len(losses)) if losses else 0.0,
        "reasons": reasons,
    }


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--source", choices=["gbm", "yfinance"], default="gbm")
    p.add_argument("--tickers", default="SPY")
    p.add_argument("--days", type=int, default=60)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--seeds", default=None, help="comma seeds to aggregate")
    p.add_argument("--min-pop", type=float, default=0.75)
    p.add_argument("--max-width", type=float, default=5.0)
    p.add_argument("--profit-target", type=float, default=0.55)
    p.add_argument("--stop-multiple", type=float, default=2.0)
    p.add_argument("--max-per-day", type=int, default=2)
    p.add_argument("--account-size", type=float, default=5_000.0)
    p.add_argument("--risk-pct", type=float, default=0.02)
    p.add_argument("--gbm-start-price", type=float, default=560.0)
    p.add_argument("--gbm-vol", type=float, default=0.18)
    p.add_argument("--base-iv", type=float, default=0.20)
    a = p.parse_args(argv)

    seeds = [int(s) for s in a.seeds.split(",")] if a.seeds else [a.seed]
    tickers = tuple(t.strip().upper() for t in a.tickers.split(",") if t.strip())

    all_trades = []
    per_seed = []
    for sd in seeds:
        cfg = BacktestConfig(
            source=a.source, tickers=tickers, days=a.days, seed=sd,
            account_size=a.account_size, risk_per_trade_pct=a.risk_pct,
            gbm_start_price=a.gbm_start_price, gbm_annual_vol=a.gbm_vol,
            base_iv=a.base_iv,
        ).normalized()
        tr = run(cfg, min_pop=a.min_pop, max_width=a.max_width,
                 profit_target=a.profit_target, stop_multiple=a.stop_multiple,
                 max_per_day=a.max_per_day)
        all_trades += tr
        per_seed.append((sd, summarize(tr)))

    m = summarize(all_trades)
    print("=" * 60)
    print("  CREDIT-SPREAD BACKTEST")
    print("=" * 60)
    print(f"  source={a.source} tickers={','.join(tickers)} days={a.days} seeds={seeds}")
    print(f"  min_pop={a.min_pop} max_width={a.max_width} "
          f"profit_target={a.profit_target} stop={a.stop_multiple}x max/day={a.max_per_day}")
    print("-" * 60)
    if not m.get("trades"):
        print("  No spreads met the gates.")
        return 0
    print(f"  Trades taken   : {m['trades']}")
    print(f"  WIN RATE       : {m['win_rate']*100:.1f}%")
    print(f"  Net P&L        : ${m['net']:,.2f}")
    print(f"  Expectancy/trd : ${m['expectancy']:.2f}")
    pf = m["profit_factor"]
    print(f"  Profit factor  : {'inf' if pf == float('inf') else f'{pf:.2f}'}")
    print(f"  Avg win / loss : ${m['avg_win']:.2f} / ${m['avg_loss']:.2f}")
    print(f"  Exit reasons   : {m['reasons']}")
    print("-" * 60)
    start = a.account_size
    final = start + m["net"]
    print(f"  Starting equity: ${start:,.2f}")
    print(f"  Final equity   : ${final:,.2f}  ({(final/start-1)*100:+.1f}%)")
    if len(per_seed) > 1:
        print("-" * 60)
        for sd, s in per_seed:
            if s.get("trades"):
                print(f"  seed {sd:<5}: win {s['win_rate']*100:5.1f}%  "
                      f"net ${s['net']:>9.2f}  ({s['trades']} trades)")
    print("-" * 60)
    print("  SIMULATION — real SPY daily bars, SYNTHETIC 0DTE option chains "
          "(real intraday option quotes aren't free). Not investment advice.")
    return 0


if __name__ == "__main__":
    import sys
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    raise SystemExit(main())
