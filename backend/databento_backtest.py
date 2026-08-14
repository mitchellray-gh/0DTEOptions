"""REAL-DATA credit-spread backtest using Databento OPRA cbbo-1m files.

Unlike ``spread_backtest.py`` (synthetic Black-Scholes chains), this settles the
app's credit-spread suggestions against **actual historical NBBO bid/ask** from
Databento's OPRA feed — the genuine, non-simulated validation.

Pipeline per trading day:
  1. Decode the day's ``opra-pillar-YYYYMMDD.cbbo-1m.dbn.zst``.
  2. Keep only that day's 0DTE contracts (expiry == file date).
  3. At the chosen ENTRY minute, build a real chain snapshot (strike/bid/ask),
     derive the underlying spot via put-call parity, back out each contract's
     implied vol from its real mid, and run the SAME spread builder the app uses
     (``backend.spreads.build_credit_spreads``, POP gate included).
  4. Settle every suggested spread at the day's real CLOSE underlying (derived
     from the last minute's parity) — a 0DTE vertical pays off purely on where
     the underlying finishes vs. the strikes.

Run:
  python -m backend.databento_backtest --dir Databento --entry 14:00 \
      --min-pop 0.85 --max-width 5 --account-size 1000 --risk-pct 0.05
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import os
import re

from backend import spreads
from backend.pricing import implied_vol

# OSI symbol: "SPY   260831C00779000" -> root, expiry, C/P, strike*1000
_OSI = re.compile(r"^(?P<root>[A-Z]+)\s+(?P<ymd>\d{6})(?P<cp>[CP])(?P<strike>\d{8})$")
_RISK_FREE = 0.045
_SESSION_END_UTC_HOUR = 20  # 16:00 ET


def _parse_osi(sym: str):
    m = _OSI.match(str(sym).strip())
    if not m:
        return None
    try:
        exp = dt.date(2000 + int(m["ymd"][:2]), int(m["ymd"][2:4]), int(m["ymd"][4:6]))
    except ValueError:
        return None
    return m["root"], exp, ("call" if m["cp"] == "C" else "put"), int(m["strike"]) / 1000.0


def _derive_spot(rows_by_type_strike: dict) -> float | None:
    """Derive the underlying via put-call parity at the most ATM strike.

    C - P ≈ S - K  (rT tiny for 0DTE) -> S ≈ K + (C_mid - P_mid), using the
    strike where |C_mid - P_mid| is smallest (closest to ATM).
    """
    best = None
    for strike, sides in rows_by_type_strike.items():
        c = sides.get("call")
        p = sides.get("put")
        if c is None or p is None:
            continue
        diff = abs(c - p)
        if best is None or diff < best[0]:
            best = (diff, strike + (c - p))
    return best[1] if best else None


def _cache_path(path: str) -> str:
    """Compact per-day 0DTE cache next to the raw file (fast re-runs)."""
    base = os.path.basename(path).replace(".dbn.zst", "")
    cache_dir = os.path.join(os.path.dirname(path), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"{base}.0dte.parquet")


def _load_0dte_frame(path: str, file_date: dt.date):
    """Decode a day's file to a COMPACT 0DTE frame and cache it as parquet.

    The raw cbbo-1m file is ~5.6M rows; the 0DTE slice is ~80k. We cache that
    slice so re-running the backtest at any entry time / gate is near-instant.
    Returns a DataFrame with columns: symbol, _ptype, _strike, bid, ask, _mid, _hm.
    """
    import pandas as pd

    cache = _cache_path(path)
    if os.path.exists(cache):
        return pd.read_parquet(cache)

    import databento as db
    store = db.DBNStore.from_file(path)
    df = store.to_df()
    if df.empty:
        return None

    parsed = df["symbol"].map(_parse_osi)
    df = df.assign(_parsed=parsed.values)
    df = df[df["_parsed"].map(lambda p: p is not None and p[1] == file_date)].copy()
    if df.empty:
        return None
    df["_ptype"] = df["_parsed"].map(lambda p: p[2])
    df["_strike"] = df["_parsed"].map(lambda p: p[3])
    df["_mid"] = (df["bid_px_00"] + df["ask_px_00"]) / 2.0
    df = df[(df["bid_px_00"] > 0) & (df["ask_px_00"] > 0) &
            (df["ask_px_00"] >= df["bid_px_00"])]
    if df.empty:
        return None
    df["_hm"] = [f"{t.hour:02d}:{t.minute:02d}" for t in df.index]
    out = df[["symbol", "_ptype", "_strike", "bid_px_00", "ask_px_00", "_mid", "_hm"]].copy()
    out = out.rename(columns={"bid_px_00": "bid", "ask_px_00": "ask"})
    try:
        out.to_parquet(cache, index=False)
    except Exception:
        pass  # caching is best-effort
    return out


def _load_snapshot(path: str, entry_minute: str, file_date: dt.date):
    """Return the entry chain + entry/close spot for one day.

    entry_chain_rows: {"calls": [...], "puts": [...]} with real bid/ask + a
    back-solved impliedVolatility, ready for build_credit_spreads.
    """
    df = _load_0dte_frame(path, file_date)
    if df is None or df.empty:
        return None

    minutes_sorted = sorted(set(df["_hm"]))
    entry_hm = next((m for m in minutes_sorted if m >= entry_minute), None)
    if entry_hm is None:
        return None
    entry = df[df["_hm"] == entry_hm]
    # Settlement close: last quoted minute AT OR BEFORE 16:00 ET (20:00 UTC).
    pre_close = [m for m in minutes_sorted if m <= "20:00"]
    close_hm = pre_close[-1] if pre_close else minutes_sorted[-1]
    close = df[df["_hm"] == close_hm]

    def _chain(frame):
        by_ts: dict[float, dict] = {}
        for _, r in frame.iterrows():
            by_ts.setdefault(r["_strike"], {})[r["_ptype"]] = float(r["_mid"])
        return by_ts

    entry_spot = _derive_spot(_chain(entry))
    close_spot = _derive_spot(_chain(close))
    if entry_spot is None or close_spot is None:
        return None

    # Minutes to 16:00 ET from the entry minute.
    eh, em = map(int, entry_hm.split(":"))
    minutes_to_expiry = max((_SESSION_END_UTC_HOUR - eh) * 60 - em, 1)
    T = minutes_to_expiry / (60 * 24 * 365)

    calls, puts = [], []
    for _, r in entry.iterrows():
        K = float(r["_strike"])
        mid = float(r["_mid"])
        otype = r["_ptype"]
        iv = implied_vol(mid, entry_spot, K, T, _RISK_FREE, otype) or 0.0
        row = {
            "contractSymbol": str(r["symbol"]).strip(),
            "strike": K,
            "bid": float(r["bid"]),
            "ask": float(r["ask"]),
            "lastPrice": mid,
            "volume": 0,
            "openInterest": 1000,  # cbbo has no OI; not used by the gate
            "impliedVolatility": iv,
        }
        (calls if otype == "call" else puts).append(row)

    return {
        "calls": calls, "puts": puts,
        "entry_spot": entry_spot, "close_spot": close_spot,
        "minutes": minutes_to_expiry, "entry_hm": entry_hm, "close_hm": close_hm,
    }


def _settle(sp: dict, close_spot: float) -> tuple[float, str]:
    """Realized P&L of a 0DTE credit spread at the real close (per the defined
    payoff). Returns (pnl_usd, 'win'|'loss')."""
    ks, kl = sp["short_strike"], sp["long_strike"]
    width, credit, contracts = sp["width"], sp["credit"], sp["contracts"]
    if sp["spread_type"] == "put_credit":
        short_i = max(ks - close_spot, 0.0)
        long_i = max(kl - close_spot, 0.0)
    else:
        short_i = max(close_spot - ks, 0.0)
        long_i = max(close_spot - kl, 0.0)
    close_cost = min(max(short_i - long_i, 0.0), width)
    per_share = credit - close_cost
    commission = 0.65 * contracts * 2.0 * 2.0  # 2 legs, in + out
    pnl = per_share * 100.0 * contracts - commission
    return round(pnl, 2), ("win" if pnl > 0 else "loss")


def run(data_dir: str, *, entry_minute: str, min_pop: float, max_width: float,
        account_size: float, risk_pct: float, max_per_day: int):
    files = sorted(glob.glob(os.path.join(data_dir, "opra-pillar-*.cbbo-1m.dbn.zst")))
    trades = []
    day_lines = []
    for path in files:
        m = re.search(r"opra-pillar-(\d{8})", os.path.basename(path))
        if not m:
            continue
        d = dt.datetime.strptime(m.group(1), "%Y%m%d").date()
        snap = _load_snapshot(path, entry_minute, d)
        if not snap:
            day_lines.append(f"  {d}: no usable 0DTE snapshot")
            continue
        found = spreads.build_credit_spreads(
            snap["calls"], snap["puts"], snap["entry_spot"], snap["minutes"],
            underlying="SPY", expiration=d.isoformat(),
            risk_free=_RISK_FREE, account_size=account_size,
            risk_per_trade_pct=risk_pct, max_width=max_width,
            min_pop=min_pop, max_results=max_per_day,
        )
        day_pnl = 0.0
        for sp in found[:max_per_day]:
            pnl, res = _settle(sp.to_dict(), snap["close_spot"])
            trades.append((d, sp.spread_type, sp.short_strike, sp.long_strike,
                          sp.pop, pnl, res))
            day_pnl += pnl
        day_lines.append(
            f"  {d}: entry {snap['entry_hm']} spot ${snap['entry_spot']:.2f} "
            f"-> close ${snap['close_spot']:.2f} | {len(found[:max_per_day])} spread(s) "
            f"| day P&L ${day_pnl:+.2f}")
    return trades, day_lines


def _summ(trades: list) -> dict:
    if not trades:
        return {"n": 0, "win": 0.0, "net": 0.0, "pf": 0.0}
    wins = [t for t in trades if t[6] == "win"]
    net = sum(t[5] for t in trades)
    gw = sum(t[5] for t in wins)
    gl = abs(sum(t[5] for t in trades if t[6] == "loss"))
    return {
        "n": len(trades),
        "win": len(wins) / len(trades),
        "net": net,
        "pf": float("inf") if gl == 0 else gw / gl,
    }


def sweep(data_dir: str, *, account_size: float, risk_pct: float, max_per_day: int):
    """Grid over entry time × POP × width on the REAL data (cached, fast).

    Finds which gate actually triggers enough trades AND stays profitable on
    genuine OPRA quotes — the empirical answer to 'is this tradable?'.
    """
    entries = ["13:35", "14:00", "14:30", "15:00", "15:30"]
    pops = [0.70, 0.75, 0.80, 0.85, 0.90]
    widths = [2.0, 5.0]
    rows = []
    for entry in entries:
        for pop in pops:
            for w in widths:
                trades, _ = run(data_dir, entry_minute=entry, min_pop=pop,
                                max_width=w, account_size=account_size,
                                risk_pct=risk_pct, max_per_day=max_per_day)
                s = _summ(trades)
                rows.append((entry, pop, w, s))
    # Rank by net, but only among configs with a usable sample (>=8 trades).
    rows.sort(key=lambda r: (r[3]["n"] >= 8, r[3]["net"]), reverse=True)
    print("=" * 72)
    print("  REAL-DATA GATE SWEEP (Databento OPRA) — ranked by net (min 8 trades)")
    print("=" * 72)
    print(f"  {'entry':>6} {'POP':>5} {'width':>6} {'trades':>7} {'win%':>6} {'net$':>9} {'PF':>6}")
    for entry, pop, w, s in rows[:20]:
        pf = 'inf' if s['pf'] == float('inf') else f"{s['pf']:.2f}"
        print(f"  {entry:>6} {pop:>5.2f} {w:>6.1f} {s['n']:>7} "
              f"{s['win']*100:>5.1f} {s['net']:>9.2f} {pf:>6}")
    return rows


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m backend.databento_backtest")
    p.add_argument("--dir", default="Databento")
    p.add_argument("--entry", default="14:00", help="entry minute UTC HH:MM")
    p.add_argument("--min-pop", type=float, default=0.85)
    p.add_argument("--max-width", type=float, default=5.0)
    p.add_argument("--account-size", type=float, default=1000.0)
    p.add_argument("--risk-pct", type=float, default=0.05)
    p.add_argument("--max-per-day", type=int, default=2)
    p.add_argument("--sweep", action="store_true",
                   help="grid entry×POP×width to find the best real-data gate")
    a = p.parse_args(argv)

    if a.sweep:
        sweep(a.dir, account_size=a.account_size, risk_pct=a.risk_pct,
              max_per_day=a.max_per_day)
        return 0

    trades, day_lines = run(
        a.dir, entry_minute=a.entry, min_pop=a.min_pop, max_width=a.max_width,
        account_size=a.account_size, risk_pct=a.risk_pct, max_per_day=a.max_per_day)

    print("=" * 66)
    print("  REAL-DATA CREDIT-SPREAD BACKTEST (Databento OPRA cbbo-1m)")
    print("=" * 66)
    for line in day_lines:
        print(line)
    print("-" * 66)
    if not trades:
        print("  No spreads met the gate on any day.")
        return 0
    wins = [t for t in trades if t[6] == "win"]
    net = sum(t[5] for t in trades)
    gw = sum(t[5] for t in wins)
    gl = abs(sum(t[5] for t in trades if t[6] == "loss"))
    print(f"  Trades           : {len(trades)}")
    print(f"  WIN RATE (REAL)  : {len(wins)/len(trades)*100:.1f}%")
    print(f"  Net P&L          : ${net:,.2f}")
    print(f"  Profit factor    : {'inf' if gl == 0 else f'{gw/gl:.2f}'}")
    print(f"  Avg win / loss   : ${(gw/len(wins)) if wins else 0:.2f} / "
          f"${(gl/(len(trades)-len(wins))) if len(trades) > len(wins) else 0:.2f}")
    print(f"  Start -> End      : ${a.account_size:,.2f} -> ${a.account_size + net:,.2f} "
          f"({net/a.account_size*100:+.1f}%)")
    print("-" * 66)
    print("  REAL Databento NBBO bid/ask. Settled at real close via put-call")
    print("  parity. Entry mid-session; commissions modeled. Educational only.")
    return 0


if __name__ == "__main__":
    import sys
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    raise SystemExit(main())
