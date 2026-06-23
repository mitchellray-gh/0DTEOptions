"""Command-line interface for the backtester.

Examples
--------
Offline simulation (no network), 120 days on a synthetic SPY-like underlying::

    python -m backend.backtest --source gbm --days 120 --seed 7

Simulation on real historical SPY daily bars::

    python -m backend.backtest --source yfinance --tickers SPY,QQQ --days 60

Settle real recorded live scans (after their contracts expired)::

    python -m backend.backtest replay --snapshots snapshots/

Dump full results to JSON::

    python -m backend.backtest --days 250 --json out.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys

from .engine import run_backtest
from .models import BacktestConfig, BacktestResult
from .replay import run_replay


def _fmt_money(x: float) -> str:
    return f"${x:,.2f}"


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _fmt_pf(x: float) -> str:
    return "inf" if x == math.inf else f"{x:.2f}"


def print_report(result: BacktestResult, *, max_trades: int = 10) -> None:
    m = result.metrics
    cfg = result.config
    print()
    print("=" * 66)
    print("  0DTE OPTIONS SCANNER — BACKTEST REPORT")
    print("=" * 66)
    mode = cfg.get("mode", cfg.get("source", "?"))
    print(f"  Mode/source      : {mode}")
    if "tickers" in cfg:
        print(f"  Tickers          : {', '.join(cfg['tickers'])}")
    print(f"  Trading days     : {len(result.day_records) or 'n/a'}")
    print(f"  Trades taken     : {m['total_trades']}")
    print("-" * 66)
    print(f"  Starting equity  : {_fmt_money(m['starting_equity'])}")
    print(f"  Final equity     : {_fmt_money(m['final_equity'])}")
    print(f"  Net P&L          : {_fmt_money(m['net_pnl'])}  ({_fmt_pct(m['total_return_pct'])})")
    print(f"  Max drawdown     : {_fmt_money(m['max_drawdown_usd'])}  ({_fmt_pct(m['max_drawdown_pct'])})")
    if m["total_trades"]:
        print("-" * 66)
        print(f"  Win rate         : {_fmt_pct(m['win_rate'])}  ({m['wins']}W / {m['losses']}L)")
        print(f"  Profit factor    : {_fmt_pf(m['profit_factor'])}")
        print(f"  Expectancy/trade : {_fmt_money(m['expectancy'])}  ({_fmt_pct(m['avg_return_pct'])})")
        print(f"  Avg win / loss   : {_fmt_money(m['avg_win'])} / {_fmt_money(m['avg_loss'])}")
        print(f"  Best / worst     : {_fmt_money(m['best_trade'])} / {_fmt_money(m['worst_trade'])}")
        print(f"  Sharpe (ann.)    : {m['sharpe']:.2f}")
        print("-" * 66)
        print("  Exits by reason:")
        for reason, cell in sorted(m["by_exit_reason"].items()):
            print(f"    {reason:<12} {cell['count']:>4} trades   {_fmt_money(cell['pnl'])}")
        print("  By option type:")
        for otype, cell in sorted(m["by_option_type"].items()):
            print(f"    {otype:<12} {cell['count']:>4} trades   {_fmt_money(cell['pnl'])}")
        print("-" * 66)
        attr = m["pnl_attribution"]
        print("  P&L attribution (assigned to source):")
        print(f"    Underlying move : {_fmt_money(attr['underlying'])}")
        print(f"    Vol reversion   : {_fmt_money(attr['vol_reversion'])}")
        print(f"    Time decay      : {_fmt_money(attr['time_decay'])}")
        print(f"    Execution/fill  : {_fmt_money(attr['execution'])}")
        print(f"    Commission      : {_fmt_money(attr['commission'])}")
        print(f"    {'→ Net P&L':<16}: {_fmt_money(m['net_pnl'])}")
        print("  Plan alignment (realized vs assigned targets):")
        print(f"    Planned target  : {_fmt_money(m['total_planned_profit'])}")
        print(f"    Planned max loss: {_fmt_money(m['total_planned_max_loss'])}")
        print(f"    Plan capture    : {_fmt_pct(m['plan_capture_ratio'])} of assigned target realized")
        print(f"    Target capture  : {_fmt_pct(m['avg_target_capture_pct'])} avg/trade")
        print(f"    Avg planned R:R : {m['avg_planned_rr']:.2f} : 1")

    if result.trades and max_trades > 0:
        print("-" * 66)
        print(f"  Sample trades (first {min(max_trades, len(result.trades))}):")
        print(f"    {'date':<11}{'sym':<20}{'entry':>7}{'exit':>7}{'qty':>4}"
              f"{'reason':>12}{'pnl':>9}{'cap%':>7}")
        for t in result.trades[:max_trades]:
            print(f"    {t.date:<11}{t.symbol[:19]:<20}{t.entry_price:>7.2f}"
                  f"{t.exit_price:>7.2f}{t.contracts:>4}{t.exit_reason:>12}"
                  f"{t.pnl_usd:>9.2f}{t.target_capture_pct * 100:>6.0f}%")

    for note in result.notes:
        print(f"  NOTE: {note}")
    print("-" * 66)
    print("  " + result.disclaimer)
    print("=" * 66)
    print()


def _build_config(args: argparse.Namespace) -> BacktestConfig:
    tickers = tuple(t.strip().upper() for t in args.tickers.split(",") if t.strip())
    return BacktestConfig(
        source=args.source,
        tickers=tickers or ("SPY",),
        days=args.days,
        start=args.start,
        end=args.end,
        seed=args.seed,
        account_size=args.account_size,
        risk_per_trade_pct=args.risk_per_trade_pct,
        risk_free_rate=args.risk_free_rate,
        max_trades_per_day=args.max_trades_per_day,
        base_iv=args.base_iv,
        iv_noise=args.iv_noise,
        mean_reversion=args.mean_reversion,
        reversion_prob=args.reversion_prob,
        commission_per_contract=args.commission,
        gbm_start_price=args.gbm_start_price,
        gbm_annual_vol=args.gbm_vol,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m backend.backtest",
        description="Backtest the 0DTE options scanner strategy.",
    )
    sub = p.add_subparsers(dest="command")

    # --- replay subcommand ---
    rp = sub.add_parser("replay", help="settle recorded live scan snapshots")
    rp.add_argument("--snapshots", required=True,
                    help="path to a snapshot .json file or a directory of them")
    rp.add_argument("--commission", type=float, default=0.65)
    rp.add_argument("--starting-equity", type=float, default=None)
    rp.add_argument("--json", default=None, help="write full results to this file")

    # --- simulate options (default command) ---
    p.add_argument("--source", choices=["gbm", "yfinance"], default="gbm")
    p.add_argument("--tickers", default="SPY")
    p.add_argument("--days", type=int, default=60)
    p.add_argument("--start", default=None, help="yfinance start date YYYY-MM-DD")
    p.add_argument("--end", default=None, help="yfinance end date YYYY-MM-DD")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--account-size", type=float, default=5_000.0)
    p.add_argument("--risk-per-trade-pct", type=float, default=0.02)
    p.add_argument("--risk-free-rate", type=float, default=0.045)
    p.add_argument("--max-trades-per-day", type=int, default=3)
    p.add_argument("--base-iv", type=float, default=0.20)
    p.add_argument("--iv-noise", type=float, default=0.03)
    p.add_argument("--mean-reversion", type=float, default=0.6,
                   help="mean fraction a cheap quote reverts toward chain IV")
    p.add_argument("--reversion-prob", type=float, default=0.55,
                   help="probability a given mispricing reverts at all")
    p.add_argument("--commission", type=float, default=0.65)
    p.add_argument("--gbm-start-price", type=float, default=500.0)
    p.add_argument("--gbm-vol", type=float, default=0.20)
    p.add_argument("--json", default=None, help="write full results to this file")
    p.add_argument("--max-sample-trades", type=int, default=10)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "replay":
        result = run_replay(args.snapshots,
                            commission_per_contract=args.commission,
                            starting_equity=args.starting_equity)
    else:
        result = run_backtest(_build_config(args))

    print_report(result, max_trades=getattr(args, "max_sample_trades", 10))

    if getattr(args, "json", None):
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result.to_dict(), fh, indent=2, default=str)
        print(f"Full results written to {args.json}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
