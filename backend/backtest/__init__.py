"""Backtesting toolkit for the 0DTE options scanner strategy.

Two ways to evaluate the strategy:

* :func:`run_backtest` -- a Monte-Carlo simulation. Generates synthetic 0DTE
  chains (or Brownian-bridge paths from real daily bars), runs the *live*
  scanner scoring + trade-plan code on them, and settles each trade. Offline and
  deterministic in ``gbm`` mode.
* :func:`run_replay` -- settles previously recorded live scan snapshots against
  the underlying's actual settlement close (real data, hold-to-expiry).

Both return a :class:`BacktestResult`. See :mod:`backend.backtest.cli` (run as
``python -m backend.backtest``) for the command-line interface.
"""
from __future__ import annotations

from .engine import DISCLAIMER, run_backtest
from .metrics import compute_metrics
from .models import BacktestConfig, BacktestResult, DayRecord
from .replay import run_replay, settle_recorded
from .settlement import BacktestTrade, settle_trade

__all__ = [
    "BacktestConfig",
    "BacktestResult",
    "BacktestTrade",
    "DayRecord",
    "DISCLAIMER",
    "compute_metrics",
    "run_backtest",
    "run_replay",
    "settle_recorded",
    "settle_trade",
]
