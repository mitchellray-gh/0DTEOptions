"""Trade settlement / P&L engine for the backtester.

Given an :class:`~backend.models.Opportunity` the scanner flagged and the
:class:`~backend.models.TradePlan` it produced, this module simulates how that
long-option position would have played out over the rest of the trading day and
returns the realized profit or loss.

Exit logic mirrors the live trade plan exactly:

* **Entry**       BUY TO OPEN at the ask (``plan.limit_price``).
* **Take-profit** SELL TO CLOSE if the contract trades up to
  ``plan.target_exit_price`` (halfway between the ask and Black-Scholes fair
  value).
* **Stop-loss**   SELL TO CLOSE if the contract trades down to
  ``plan.stop_loss_price`` (50% of premium).
* **Expiry**      whatever is left settles at intrinsic value at the close.

Intraday repricing uses Black-Scholes with two moving inputs:

1. The underlying follows the supplied intraday price ``path`` (real
   OHLC-derived or simulated).
2. The contract's own implied vol drifts from the (cheap) IV implied by its
   entry ask back toward the chain's reference IV by ``reversion_fraction``.
   This models the core thesis of the scanner -- a stale/cheap quote reverting
   to the chain consensus. ``reversion_fraction == 0`` means the discount never
   closes and the trade lives or dies purely on the underlying's move.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..models import Opportunity, TradePlan
from ..pricing import bs_price, implied_vol

_YEAR_MINUTES = 60 * 24 * 365


@dataclass
class BacktestTrade:
    """A fully-resolved simulated trade with its P&L attribution."""
    date: str
    underlying: str
    symbol: str
    option_type: str
    strike: float
    entry_underlying: float
    exit_underlying: float
    entry_price: float
    exit_price: float
    contracts: int
    fair_value: float
    reference_iv: float
    entry_iv: float
    edge_pct: float
    reversion_fraction: float
    exit_reason: str          # 'take_profit' | 'stop_loss' | 'expiry'
    hold_minutes: int
    capital_usd: float
    gross_pnl_usd: float
    commission_usd: float
    pnl_usd: float
    return_pct: float         # pnl / capital deployed

    # --- assigned plan targets (straight from the live TradePlan) ---
    planned_target_usd: float = 0.0      # plan.target_profit_usd
    planned_max_loss_usd: float = 0.0    # plan.max_loss_usd
    planned_rr: float = 0.0              # assigned reward : risk ratio
    target_capture_pct: float = 0.0      # realized pnl / planned target

    # --- realized P&L assigned to its drivers (sums to gross_pnl_usd) ---
    pnl_underlying_usd: float = 0.0      # delta/gamma: the underlying's move
    pnl_vol_usd: float = 0.0             # vega: IV reversion toward reference
    pnl_time_usd: float = 0.0            # theta: time decay
    pnl_execution_usd: float = 0.0       # fill-vs-model mark + entry edge + slippage


def _intrinsic(spot: float, strike: float, option_type: str) -> float:
    if option_type == "call":
        return max(spot - strike, 0.0)
    return max(strike - spot, 0.0)


def settle_trade(
    opp: Opportunity,
    plan: TradePlan,
    path: Sequence[float],
    *,
    date: str,
    risk_free: float,
    reversion_fraction: float,
    minutes_to_expiry: int,
    commission_per_contract: float = 0.65,
    exit_slippage_pct: float = 0.0,
) -> BacktestTrade:
    """Resolve a single long-option trade against an intraday underlying path.

    ``path[0]`` is the underlying at entry (== ``opp.underlying_price``) and
    ``path[-1]`` is the settlement price at expiry. Intermediate points are
    repricing checkpoints for take-profit / stop-loss.
    """
    S0 = float(opp.underlying_price)
    K = float(opp.strike)
    otype = opp.option_type
    entry = float(plan.limit_price)            # == opp.ask
    tp = float(plan.target_exit_price)
    sl = float(plan.stop_loss_price)
    contracts = int(plan.suggested_contracts)
    ref_iv = float(opp.reference_iv)

    T0 = max(minutes_to_expiry, 1) / _YEAR_MINUTES

    # IV implied by the entry ask -- typically *below* ref_iv (that gap is the
    # edge). Drift target is a partial reversion back toward the chain IV.
    entry_iv = implied_vol(entry, S0, K, T0, risk_free, otype)
    if entry_iv is None or entry_iv <= 0:
        entry_iv = ref_iv
    target_iv = entry_iv + reversion_fraction * (ref_iv - entry_iv)

    n = max(len(path) - 1, 1)
    exit_price: float | None = None
    exit_reason = "expiry"
    hold_minutes = minutes_to_expiry
    exit_underlying = float(path[-1])
    exit_frac = 1.0           # fraction of the session elapsed at exit

    # Walk the intraday checkpoints (indices 1..n-1, all with T > 0). The final
    # point (index n) is expiry and always settles at intrinsic value below.
    for k in range(1, n):
        frac = k / n
        S_k = float(path[k])
        T_k = T0 * (1.0 - frac)
        iv_k = entry_iv + frac * (target_iv - entry_iv)
        mark = bs_price(S_k, K, T_k, risk_free, max(iv_k, 1e-6), otype)

        # Conservative ordering: a checkpoint that straddles both the stop and
        # the target is booked as a stop-out.
        if mark <= sl:
            exit_price, exit_reason = sl, "stop_loss"
            hold_minutes = max(int(minutes_to_expiry * frac), 1)
            exit_underlying = S_k
            exit_frac = frac
            break
        if mark >= tp:
            exit_price, exit_reason = tp, "take_profit"
            hold_minutes = max(int(minutes_to_expiry * frac), 1)
            exit_underlying = S_k
            exit_frac = frac
            break

    if exit_price is None:
        # Survived to the close -> intrinsic settlement.
        S_T = float(path[-1])
        exit_price = _intrinsic(S_T, K, otype)
        exit_reason = "expiry"
        hold_minutes = minutes_to_expiry
        exit_underlying = S_T
        exit_frac = 1.0

    # Take-profit / stop fills give up a touch to slippage; expiry settles clean.
    realized_exit = exit_price
    if exit_reason in ("take_profit", "stop_loss"):
        realized_exit = exit_price * (1.0 - exit_slippage_pct)

    mult = 100.0 * contracts
    capital = entry * mult
    gross = (realized_exit - entry) * mult
    commission = commission_per_contract * contracts * 2.0
    pnl = gross - commission
    return_pct = pnl / capital if capital > 0 else 0.0

    # --- assign the realized gross P&L to its drivers (a repricing waterfall) ---
    # Step the Black-Scholes inputs from entry to exit one at a time, so each
    # bucket is the value change attributable to that single input. The three
    # model buckets telescope to the model's value change; the execution bucket
    # absorbs the gap between the model mark and the actual fill (take-profit /
    # stop-loss are fixed price levels) plus any entry edge. By construction the
    # four buckets sum to gross_pnl_usd exactly.
    sigma0 = max(entry_iv, 1e-6)
    sigma1 = max(entry_iv + exit_frac * (target_iv - entry_iv), 1e-6)
    T1 = max(T0 * (1.0 - exit_frac), 0.0)
    v0 = bs_price(S0, K, T0, risk_free, sigma0, otype)
    v_s = bs_price(exit_underlying, K, T0, risk_free, sigma0, otype)
    v_sv = bs_price(exit_underlying, K, T0, risk_free, sigma1, otype)
    v_svt = (bs_price(exit_underlying, K, T1, risk_free, sigma1, otype)
             if T1 > 0 else _intrinsic(exit_underlying, K, otype))
    gross_r = round(gross, 2)
    pnl_underlying = round((v_s - v0) * mult, 2)
    pnl_vol = round((v_sv - v_s) * mult, 2)
    pnl_time = round((v_svt - v_sv) * mult, 2)
    # Execution is the exact balancing item so the buckets reconcile to gross.
    pnl_execution = round(gross_r - pnl_underlying - pnl_vol - pnl_time, 2)

    # --- align the realized result against the plan's assigned targets ---
    planned_target = float(plan.target_profit_usd)
    planned_max_loss = float(plan.max_loss_usd)
    planned_rr = planned_target / planned_max_loss if planned_max_loss > 0 else 0.0
    target_capture = pnl / planned_target if planned_target > 0 else 0.0

    return BacktestTrade(
        date=date,
        underlying=opp.underlying,
        symbol=opp.symbol,
        option_type=otype,
        strike=K,
        entry_underlying=round(S0, 4),
        exit_underlying=round(exit_underlying, 4),
        entry_price=round(entry, 4),
        exit_price=round(realized_exit, 4),
        contracts=contracts,
        fair_value=round(float(opp.fair_value), 4),
        reference_iv=round(ref_iv, 4),
        entry_iv=round(float(entry_iv), 4),
        edge_pct=round(float(opp.edge_pct), 4),
        reversion_fraction=round(float(reversion_fraction), 4),
        exit_reason=exit_reason,
        hold_minutes=hold_minutes,
        capital_usd=round(capital, 2),
        gross_pnl_usd=gross_r,
        commission_usd=round(commission, 2),
        pnl_usd=round(pnl, 2),
        return_pct=round(return_pct, 4),
        planned_target_usd=round(planned_target, 2),
        planned_max_loss_usd=round(planned_max_loss, 2),
        planned_rr=round(planned_rr, 3),
        target_capture_pct=round(target_capture, 4),
        pnl_underlying_usd=pnl_underlying,
        pnl_vol_usd=pnl_vol,
        pnl_time_usd=pnl_time,
        pnl_execution_usd=pnl_execution,
    )
