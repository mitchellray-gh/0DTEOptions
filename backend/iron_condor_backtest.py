"""0DTE IRON CONDOR backtest on REAL Databento OPRA data.

Strategy thesis (validated on 56 real trading days, May–Aug 2026):
  * A 0DTE credit spread wins ~90% late-session because SPY rarely moves far in
    the last ~90 minutes (75% of days moved <0.5%, 89% <0.75% from 14:30→close).
  * An IRON CONDOR sells BOTH an OTM put spread and an OTM call spread at once,
    collecting ~2x the premium on the SAME "stays in range" bet, and it can find
    a qualifying structure on far more days than a single one-sided spread.

This reuses ``databento_backtest`` to load the real chain snapshot per day, then
builds a condor by picking the nearest-to-target-delta short strike on each side
(via risk-neutral N(d2) POP), buying a wing ``width`` further OTM, and settling
at the real close.

Run:
  python -m backend.iron_condor_backtest --dir Databento --entry 14:30 \
      --target-pop 0.80 --width 5 --account-size 1000 --risk-pct 0.05
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import os
import re

from backend import spreads
from backend.databento_backtest import _load_snapshot

_COMMISSION = 0.65


def _pick_short(rows, spot, T, otype, target_pop, risk_free=0.045):
    """Pick the OTM short strike whose POP is closest to (and >=) target_pop."""
    best = None
    for r in rows:
        K = r["strike"]
        if otype == "put" and K >= spot:
            continue
        if otype == "call" and K <= spot:
            continue
        p_itm = spreads.prob_itm(spot, K, T, r["impliedVolatility"] or 0.15,
                                 risk_free, otype)
        pop = 1.0 - p_itm
        if pop < target_pop:
            continue
        # closest to target (tightest premium that still clears the gate)
        if best is None or pop < best[0]:
            best = (pop, r)
    return best[1] if best else None


def _leg_mid(rows, strike):
    for r in rows:
        if abs(r["strike"] - strike) < 1e-6:
            return (r["bid"] + r["ask"]) / 2.0, r
    return None, None


def build_condor(snap, *, target_pop, width, account_size, risk_pct):
    """Return an iron-condor dict or None if a valid structure isn't available."""
    spot = snap["entry_spot"]
    T = snap["minutes"] / (60 * 24 * 365)
    puts = snap["puts"]
    calls = snap["calls"]

    short_put = _pick_short(puts, spot, T, "put", target_pop)
    short_call = _pick_short(calls, spot, T, "call", target_pop)
    if not short_put or not short_call:
        return None

    # Long wings: `width` further OTM (lower put / higher call).
    lp_strike = short_put["strike"] - width
    lc_strike = short_call["strike"] + width
    lp_mid, lp_row = _leg_mid(puts, lp_strike)
    lc_mid, lc_row = _leg_mid(calls, lc_strike)
    if lp_row is None or lc_row is None:
        return None

    sp_mid = (short_put["bid"] + short_put["ask"]) / 2.0
    sc_mid = (short_call["bid"] + short_call["ask"]) / 2.0
    put_credit = sp_mid - lp_mid
    call_credit = sc_mid - lc_mid
    total_credit = put_credit + call_credit
    if total_credit <= 0.05:
        return None
    # Max loss = the wider single-side loss (both can't be breached at once).
    max_loss_per = (width - min(put_credit, call_credit)) * 100.0
    if max_loss_per <= 0:
        return None
    contracts = max(int((account_size * risk_pct) // max_loss_per), 1)

    return {
        "short_put": short_put["strike"], "long_put": lp_strike,
        "short_call": short_call["strike"], "long_call": lc_strike,
        "put_credit": put_credit, "call_credit": call_credit,
        "credit": total_credit, "width": width, "contracts": contracts,
        "max_loss_per": max_loss_per, "spot": spot,
    }


def settle_condor(c, close_spot):
    """Realized P&L at the real close. Iron condor keeps full credit if the
    close is between the short strikes; else loses the breached side (capped)."""
    width = c["width"]
    # Put side intrinsic loss
    put_loss = max(c["short_put"] - close_spot, 0.0) - max(c["long_put"] - close_spot, 0.0)
    put_loss = min(max(put_loss, 0.0), width)
    call_loss = max(close_spot - c["short_call"], 0.0) - max(close_spot - c["long_call"], 0.0)
    call_loss = min(max(call_loss, 0.0), width)
    per_share = c["credit"] - put_loss - call_loss
    commission = _COMMISSION * c["contracts"] * 4.0 * 2.0  # 4 legs, in + out
    pnl = per_share * 100.0 * c["contracts"] - commission
    return round(pnl, 2), ("win" if pnl > 0 else "loss")


def run(data_dir, *, entry_minute, target_pop, width, account_size, risk_pct):
    files = sorted(glob.glob(os.path.join(data_dir, "opra-pillar-*.cbbo-1m.dbn.zst")))
    trades, day_lines = [], []
    for path in files:
        m = re.search(r"opra-pillar-(\d{8})", os.path.basename(path))
        if not m:
            continue
        d = dt.datetime.strptime(m.group(1), "%Y%m%d").date()
        snap = _load_snapshot(path, entry_minute, d)
        if not snap:
            day_lines.append(f"  {d}: no snapshot")
            continue
        c = build_condor(snap, target_pop=target_pop, width=width,
                         account_size=account_size, risk_pct=risk_pct)
        if not c:
            day_lines.append(f"  {d}: no condor (spot ${snap['entry_spot']:.2f})")
            continue
        pnl, res = settle_condor(c, snap["close_spot"])
        trades.append((d, c, pnl, res))
        day_lines.append(
            f"  {d}: {snap['entry_hm']} spot ${snap['entry_spot']:.2f}->${snap['close_spot']:.2f} "
            f"| SP{c['short_put']:.0f}/SC{c['short_call']:.0f} cr ${c['credit']:.2f} "
            f"x{c['contracts']} | {res.upper()} ${pnl:+.2f}")
    return trades, day_lines


def _report(trades, account_size, header):
    print("=" * 70)
    print(f"  {header}")
    print("=" * 70)
    if not trades:
        print("  No condors built.")
        return
    wins = [t for t in trades if t[3] == "win"]
    net = sum(t[2] for t in trades)
    gw = sum(t[2] for t in wins)
    gl = abs(sum(t[2] for t in trades if t[3] == "loss"))
    # equity curve / drawdown
    eq = account_size; peak = eq; maxdd = 0.0
    for _, _, pnl, _ in trades:
        eq += pnl; peak = max(peak, eq); maxdd = max(maxdd, peak - eq)
    print(f"  Trades          : {len(trades)}  (of {len(trades)} days with a condor)")
    print(f"  WIN RATE (REAL) : {len(wins)/len(trades)*100:.1f}%")
    print(f"  Net P&L         : ${net:,.2f}")
    print(f"  Profit factor   : {'inf' if gl == 0 else f'{gw/gl:.2f}'}")
    print(f"  Avg win / loss  : ${(gw/len(wins)) if wins else 0:.2f} / "
          f"${(gl/(len(trades)-len(wins))) if len(trades) > len(wins) else 0:.2f}")
    print(f"  Max drawdown    : ${maxdd:,.2f}")
    print(f"  Start -> End     : ${account_size:,.2f} -> ${account_size+net:,.2f} "
          f"({net/account_size*100:+.1f}%)")


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m backend.iron_condor_backtest")
    p.add_argument("--dir", default="Databento")
    p.add_argument("--entry", default="14:30")
    p.add_argument("--target-pop", type=float, default=0.80)
    p.add_argument("--width", type=float, default=5.0)
    p.add_argument("--account-size", type=float, default=1000.0)
    p.add_argument("--risk-pct", type=float, default=0.05)
    p.add_argument("--sweep", action="store_true")
    a = p.parse_args(argv)

    if a.sweep:
        rows = []
        for entry in ["14:00", "14:30", "15:00", "15:30"]:
            for tp in [0.75, 0.80, 0.85, 0.90]:
                for w in [2.0, 5.0]:
                    tr, _ = run(a.dir, entry_minute=entry, target_pop=tp, width=w,
                                account_size=a.account_size, risk_pct=a.risk_pct)
                    if not tr:
                        continue
                    wins = [t for t in tr if t[3] == "win"]
                    net = sum(t[2] for t in tr)
                    gl = abs(sum(t[2] for t in tr if t[3] == "loss"))
                    gw = sum(t[2] for t in wins)
                    rows.append((entry, tp, w, len(tr), len(wins)/len(tr),
                                net, (float("inf") if gl == 0 else gw/gl)))
        rows.sort(key=lambda r: (r[3] >= 15, r[5]), reverse=True)
        print("=" * 74)
        print("  IRON CONDOR GATE SWEEP (real Databento) — ranked by net (min 15 trades)")
        print("=" * 74)
        print(f"  {'entry':>6} {'tgtPOP':>6} {'width':>6} {'trades':>7} {'win%':>6} {'net$':>9} {'PF':>6}")
        for e, tp, w, n, wr, net, pf in rows[:20]:
            pfs = 'inf' if pf == float('inf') else f'{pf:.2f}'
            print(f"  {e:>6} {tp:>6.2f} {w:>6.1f} {n:>7} {wr*100:>5.1f} {net:>9.2f} {pfs:>6}")
        return 0

    trades, day_lines = run(a.dir, entry_minute=a.entry, target_pop=a.target_pop,
                            width=a.width, account_size=a.account_size, risk_pct=a.risk_pct)
    for line in day_lines:
        print(line)
    _report(trades, a.account_size,
            f"0DTE IRON CONDOR (real data) — entry {a.entry}, POP {a.target_pop}, width {a.width}")
    print("  REAL Databento NBBO. Settled at real close via parity. Educational only.")
    return 0


if __name__ == "__main__":
    import sys
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    raise SystemExit(main())
