"""Configuration and result containers for the backtester."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal, Optional

DataSource = Literal["gbm", "yfinance"]


@dataclass
class BacktestConfig:
    """Everything that controls a backtest run.

    The strategy-sizing knobs (``account_size``, ``risk_per_trade_pct``,
    ``risk_free_rate``) are passed straight through to the *live* trade-plan
    builder so the backtest sizes positions exactly like the real tool.
    """

    # --- data source ---
    source: DataSource = "gbm"
    tickers: tuple[str, ...] = ("SPY",)
    days: int = 60                       # gbm: trading days per ticker
    start: Optional[str] = None          # yfinance ISO date (inclusive)
    end: Optional[str] = None            # yfinance ISO date (inclusive)
    seed: int = 42

    # --- account / strategy sizing (mirrors the live scanner) ---
    account_size: float = 5_000.0
    risk_per_trade_pct: float = 0.02
    risk_free_rate: float = 0.045
    max_trades_per_day: int = 3          # top-N opportunities taken each day

    # --- trading session ---
    session_minutes: int = 390           # 6.5h regular US session
    intraday_steps: int = 26             # repricing granularity (~15 min bars)

    # --- synthetic option-chain model (per trading day) ---
    base_iv: float = 0.20                # chain-central annualized IV
    iv_noise: float = 0.03               # per-contract IV dispersion -> mispricings
    smile_coef: float = 4.0              # volatility-smile curvature
    strike_width_pct: float = 0.08       # strikes generated within +/- this of spot
    base_volume: int = 1_500             # ATM volume; decays away from the money
    base_spread_pct: float = 0.05        # ATM bid/ask spread as a fraction of mid

    # --- gbm underlying (offline, deterministic) ---
    gbm_start_price: float = 500.0
    gbm_annual_vol: float = 0.20
    gbm_annual_drift: float = 0.05
    gbm_overnight_gap_vol: float = 0.005

    # --- mispricing reversion: the modeled alpha source ---
    # With probability ``reversion_prob`` a cheap quote drifts back toward the
    # chain reference IV by a fraction drawn from N(mean_reversion, reversion_sd).
    # 0 => the discount never closes (trade lives/dies on the underlying move).
    reversion_prob: float = 0.55
    mean_reversion: float = 0.6
    reversion_sd: float = 0.25

    # --- frictions ---
    commission_per_contract: float = 0.65   # charged on entry and exit
    exit_slippage_pct: float = 0.01         # haircut on take-profit / stop fills

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tickers"] = list(self.tickers)
        return d

    def normalized(self) -> "BacktestConfig":
        """Return a copy with tickers upper-cased and de-duplicated."""
        seen: set[str] = set()
        unique: list[str] = []
        for t in self.tickers:
            u = t.strip().upper()
            if u and u not in seen:
                seen.add(u)
                unique.append(u)
        return BacktestConfig(**{**asdict(self), "tickers": tuple(unique or ("SPY",))})


@dataclass
class DayRecord:
    """One simulated trading day's summary."""
    date: str
    underlying: str
    spot_open: float
    spot_close: float
    reference_iv: float
    n_opportunities: int
    n_trades: int
    day_pnl: float


@dataclass
class BacktestResult:
    config: dict
    trades: list           # list[BacktestTrade]
    day_records: list      # list[DayRecord]
    equity_curve: list     # list[tuple[str, float]] -> (date, equity)
    metrics: dict
    notes: list = field(default_factory=list)
    disclaimer: str = ""

    def to_dict(self) -> dict:
        return {
            "config": self.config,
            "metrics": self.metrics,
            "equity_curve": [{"date": d, "equity": e} for d, e in self.equity_curve],
            "day_records": [asdict(d) for d in self.day_records],
            "trades": [asdict(t) for t in self.trades],
            "notes": self.notes,
            "disclaimer": self.disclaimer,
        }
