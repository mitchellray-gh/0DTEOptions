"""Forward-test recorder + settler for the credit-spread strategy using REAL data.

No synthetic prices, no API key. Two commands:

  record  — snapshot today's ranked credit spreads from the LIVE app (real CBOE
            chain) to a dated JSON file. Run once per trading day near the open.
  settle  — for every recorded snapshot whose expiry has passed, look up the
            underlying's REAL closing price (Yahoo) and compute the spread's
            realized P&L (a 0DTE vertical settles purely on where the underlying
            closed vs. the strikes). Prints a real, non-simulated track record.

This is the honest way to validate the strategy: it accrues genuine forward
results over time instead of pretending we have historical option quotes.

Usage:
  python -m backend.forward_test record --tickers SPY,QQQ --dir forward
  python -m backend.forward_test settle --dir forward
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os

from backend import scanner, yahoo


def _record(tickers: list[str], out_dir: str, min_pop: float, max_width: float,
            max_per_ticker: int) -> None:
    os.makedirs(out_dir, exist_ok=True)
    spreads, notes = scanner.fetch_spreads(
        tickers, min_pop=min_pop, max_width=max_width,
        max_results=max_per_ticker * len(tickers),
    )
    stamp = dt.datetime.now(dt.timezone.utc)
    payload = {
        "recorded_at": stamp.isoformat(),
        "min_pop": min_pop,
        "max_width": max_width,
        "spreads": spreads,
        "notes": notes,
    }
    fname = os.path.join(out_dir, f"spreads-{stamp.strftime('%Y%m%d-%H%M%S')}.json")
    with open(fname, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(f"Recorded {len(spreads)} spread(s) -> {fname}")
    if not spreads:
        print("  (No spreads met the gate right now — try nearer the open.)")


def _underlying_close(ticker: str, date_iso: str) -> float | None:
    """Real settlement close for a past date via Yahoo daily bars."""
    try:
        start = dt.date.fromisoformat(date_iso)
        end = start + dt.timedelta(days=1)
        res = yahoo.chart_period(ticker.upper(), int(dt.datetime(
            start.year, start.month, start.day, tzinfo=dt.timezone.utc).timestamp()),
            int(dt.datetime(end.year, end.month, end.day,
                            tzinfo=dt.timezone.utc).timestamp()), "1d")
        bars = yahoo.bars_from_chart(res)
        return float(bars[-1]["c"]) if bars else None
    except Exception:
        return None


def _settle_spread(sp: dict, close_px: float) -> dict:
    """Realized P&L of a 0DTE vertical given the real underlying close."""
    ks, kl = sp["short_strike"], sp["long_strike"]
    width = sp["width"]
    credit = sp["credit"]
    contracts = sp["contracts"]
    if sp["spread_type"] == "put_credit":
        short_int = max(ks - close_px, 0.0)
        long_int = max(kl - close_px, 0.0)
    else:
        short_int = max(close_px - ks, 0.0)
        long_int = max(close_px - kl, 0.0)
    close_cost = min(max(short_int - long_int, 0.0), width)
    per_share = credit - close_cost
    commission = 0.65 * contracts * 2.0 * 2.0
    pnl = per_share * 100.0 * contracts - commission
    return {
        "underlying": sp["underlying"],
        "spread_type": sp["spread_type"],
        "short_strike": ks,
        "long_strike": kl,
        "expiration": sp["expiration"],
        "close_px": round(close_px, 2),
        "credit": credit,
        "pop": sp["pop"],
        "pnl_usd": round(pnl, 2),
        "win": pnl > 0,
    }


def _settle(out_dir: str) -> None:
    files = sorted(glob.glob(os.path.join(out_dir, "spreads-*.json")))
    if not files:
        print(f"No snapshots found in {out_dir}. Run 'record' first.")
        return
    today = dt.datetime.now(dt.timezone.utc).date()
    settled = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            snap = json.load(fh)
        for sp in snap.get("spreads", []):
            exp = dt.date.fromisoformat(sp["expiration"])
            if exp >= today:
                continue  # not expired yet
            close_px = _underlying_close(sp["underlying"], sp["expiration"])
            if close_px is None:
                continue
            settled.append(_settle_spread(sp, close_px))

    if not settled:
        print("No expired snapshots to settle yet. Record daily and re-run "
              "'settle' after expiries pass.")
        return

    wins = [t for t in settled if t["win"]]
    net = sum(t["pnl_usd"] for t in settled)
    print("=" * 60)
    print("  FORWARD-TEST RESULTS (REAL DATA, settled at expiry)")
    print("=" * 60)
    print(f"  Settled trades : {len(settled)}")
    print(f"  WIN RATE       : {len(wins)/len(settled)*100:.1f}%")
    print(f"  Net P&L        : ${net:,.2f}")
    print(f"  Expectancy/trd : ${net/len(settled):.2f}")
    print("-" * 60)
    for t in settled[-15:]:
        tag = "WIN " if t["win"] else "LOSS"
        print(f"  {t['expiration']} {t['underlying']} "
              f"{t['spread_type']:11} {int(t['short_strike'])}/{int(t['long_strike'])} "
              f"close ${t['close_px']:.2f}  {tag} ${t['pnl_usd']:+.2f}")
    print("-" * 60)
    print("  Real underlying closes + real recorded spreads. No synthetic prices.")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m backend.forward_test")
    sub = p.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("record", help="snapshot today's live spreads")
    rp.add_argument("--tickers", default="SPY,QQQ,IWM")
    rp.add_argument("--dir", default="forward")
    rp.add_argument("--min-pop", type=float, default=0.85)
    rp.add_argument("--max-width", type=float, default=5.0)
    rp.add_argument("--max-per-ticker", type=int, default=3)
    sp = sub.add_parser("settle", help="settle expired snapshots vs real closes")
    sp.add_argument("--dir", default="forward")
    a = p.parse_args(argv)

    if a.cmd == "record":
        tickers = [t.strip().upper() for t in a.tickers.split(",") if t.strip()]
        _record(tickers, a.dir, a.min_pop, a.max_width, a.max_per_ticker)
    else:
        _settle(a.dir)
    return 0


if __name__ == "__main__":
    import sys
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    raise SystemExit(main())
