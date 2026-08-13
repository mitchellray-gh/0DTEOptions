"""Defined-risk credit-spread engine for 0DTE.

The long-option scanner (``scanner.py``) buys premium and, per the backtester,
structurally caps near a ~65-70% win rate with negative expectancy because it
fights theta. This module implements the honest way to a *high win rate*:
**selling** defined-risk vertical credit spreads.

A credit spread sells a nearer-the-money option and buys a further-OTM option
of the same type as a hedge, for a net credit. Max profit = the credit (kept if
both expire worthless); max loss = width − credit (capped by the long leg). By
choosing short strikes with a low probability of finishing in the money, the
*probability of profit* (POP) can be 75-90%+ — the trade wins whenever the
underlying simply stays on the right side of the short strike.

Everything here is pricing/geometry only; no data fetching. It consumes the same
raw chain rows the scanner already fetches (``strike``/``bid``/``ask``/...).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Optional

from .pricing import _norm_cdf, bs_price, implied_vol

SpreadType = Literal["put_credit", "call_credit"]

# ── Quality gates ────────────────────────────────────────────────────────────
MIN_CREDIT = 0.05           # ignore spreads that collect less than a nickel
MIN_POP = 0.85              # only surface spreads with >=85% modeled win prob
                            # (backtested to ~82% realized win rate, net positive)
MIN_CREDIT_TO_WIDTH = 0.10  # credit must be >=10% of width (avoid picking pennies
                            # in front of a steamroller)
MAX_SHORT_DELTA = 0.30      # short strike no deeper than ~0.30 delta
NEAR_THE_MONEY_PCT = 0.03   # ATM band used for the chain reference IV


@dataclass
class SpreadLeg:
    strike: float
    option_type: str
    action: str            # "sell" | "buy"
    price: float           # per-share mid used for the fill


@dataclass
class CreditSpread:
    """A fully-specified 0DTE vertical credit spread with its risk/reward."""
    underlying: str
    spread_type: SpreadType
    expiration: str
    underlying_price: float
    short_strike: float
    long_strike: float
    width: float
    credit: float              # net per-share credit collected
    max_profit_usd: float      # credit * 100 * contracts
    max_loss_usd: float        # (width - credit) * 100 * contracts
    contracts: int
    reference_iv: float
    short_delta: float
    pop: float                 # modeled probability of profit (per share, at expiry)
    expected_value_usd: float  # pop*maxprofit - (1-pop)*maxloss (pre-commission)
    breakeven: float
    minutes_to_expiry: int
    reward_risk: float         # max_profit / max_loss
    score: float
    short_symbol: str = ""
    long_symbol: str = ""

    def to_dict(self) -> dict:
        return {
            "underlying": self.underlying,
            "spread_type": self.spread_type,
            "expiration": self.expiration,
            "underlying_price": round(self.underlying_price, 4),
            "short_strike": self.short_strike,
            "long_strike": self.long_strike,
            "width": round(self.width, 4),
            "credit": round(self.credit, 4),
            "max_profit_usd": round(self.max_profit_usd, 2),
            "max_loss_usd": round(self.max_loss_usd, 2),
            "contracts": self.contracts,
            "reference_iv": round(self.reference_iv, 4),
            "short_delta": round(self.short_delta, 4),
            "pop": round(self.pop, 4),
            "expected_value_usd": round(self.expected_value_usd, 2),
            "breakeven": round(self.breakeven, 4),
            "minutes_to_expiry": self.minutes_to_expiry,
            "reward_risk": round(self.reward_risk, 4),
            "score": round(self.score, 3),
            "short_symbol": self.short_symbol,
            "long_symbol": self.long_symbol,
        }


def _mid(bid: float, ask: float, last: float) -> float:
    if bid > 0 and ask > 0 and ask >= bid:
        return (bid + ask) / 2
    if last > 0:
        return last
    return max(bid, ask, 0.0)


def prob_itm(spot: float, strike: float, T: float, sigma: float, r: float,
             option_type: str) -> float:
    """Risk-neutral probability the option finishes in the money (N(d2) form).

    For a call this is P(S_T > K); for a put P(S_T < K). Used to derive the
    short leg's probability of *finishing worthless*, i.e. the spread's POP.
    """
    if T <= 0 or sigma <= 0 or spot <= 0 or strike <= 0:
        # Degenerate: fall back to intrinsic side.
        itm = (spot > strike) if option_type == "call" else (spot < strike)
        return 1.0 if itm else 0.0
    vt = sigma * math.sqrt(T)
    d2 = (math.log(spot / strike) + (r - 0.5 * sigma * sigma) * T) / vt
    return _norm_cdf(d2) if option_type == "call" else _norm_cdf(-d2)


def compute_reference_iv(rows: list[dict], spot: float) -> Optional[float]:
    """Volume-weighted IV of near-the-money contracts (mirror of scanner)."""
    lo, hi = spot * (1 - NEAR_THE_MONEY_PCT), spot * (1 + NEAR_THE_MONEY_PCT)
    num = den = 0.0
    ivs: list[float] = []
    for r in rows:
        iv = float(r.get("impliedVolatility") or 0.0)
        k = float(r.get("strike") or 0.0)
        vol = float(r.get("volume") or 0.0)
        if 0.01 < iv < 5:
            ivs.append(iv)
            if lo <= k <= hi and vol > 0:
                num += iv * max(vol, 1.0)
                den += max(vol, 1.0)
    if den > 0:
        return num / den
    if ivs:
        ivs.sort()
        return ivs[len(ivs) // 2]
    return None


def _clean_rows(rows: list[dict]) -> list[dict]:
    """Keep rows with a usable strike + a computable mid, sorted by strike."""
    out = []
    for r in rows:
        k = float(r.get("strike") or 0.0)
        mid = _mid(float(r.get("bid") or 0), float(r.get("ask") or 0),
                   float(r.get("lastPrice") or 0))
        if k > 0 and mid > 0:
            out.append({**r, "_strike": k, "_mid": mid})
    out.sort(key=lambda x: x["_strike"])
    return out


def _size_contracts(max_loss_per_spread: float, account_size: float,
                    risk_per_trade_pct: float) -> int:
    """Contracts so the defined max loss stays within the risk budget."""
    budget = account_size * risk_per_trade_pct
    if max_loss_per_spread <= 0:
        return 1
    return max(int(budget // max_loss_per_spread), 1)


def build_credit_spreads(
    calls: list[dict],
    puts: list[dict],
    spot: float,
    minutes_to_expiry: int,
    *,
    underlying: str,
    expiration: str,
    reference_iv: Optional[float] = None,
    risk_free: float = 0.045,
    account_size: float = 5_000.0,
    risk_per_trade_pct: float = 0.02,
    max_width: float = 10.0,
    min_pop: float = MIN_POP,
    max_results: int = 25,
) -> list[CreditSpread]:
    """Enumerate 0DTE vertical credit spreads and rank them by a POP-weighted
    score.

    Put credit spreads (bullish/neutral): sell a put below spot, buy a further
    OTM put. Call credit spreads (bearish/neutral): sell a call above spot, buy
    a further OTM call. Only spreads with POP >= ``min_pop`` and a sane
    credit/width survive.
    """
    T = max(minutes_to_expiry, 1) / (60 * 24 * 365)
    all_rows = calls + puts
    if reference_iv is None:
        reference_iv = compute_reference_iv(all_rows, spot)
    if reference_iv is None or reference_iv <= 0:
        return []

    results: list[CreditSpread] = []

    def _consider(short_row: dict, long_row: dict, otype: str,
                  stype: SpreadType):
        ks = short_row["_strike"]
        kl = long_row["_strike"]
        width = abs(ks - kl)
        if width <= 0 or width > max_width:
            return
        # Net credit = short mid - long mid (we sell the nearer, buy the further).
        credit = short_row["_mid"] - long_row["_mid"]
        if credit < MIN_CREDIT:
            return
        if credit >= width:  # arbitrage/quote glitch — skip
            return
        if credit / width < MIN_CREDIT_TO_WIDTH:
            return

        # Probability the SHORT leg finishes worthless == spread wins outright.
        p_short_itm = prob_itm(spot, ks, T, reference_iv, risk_free, otype)
        pop = 1.0 - p_short_itm
        if pop < min_pop:
            return

        # Short-leg delta magnitude (risk-neutral) as a depth gate.
        short_delta = p_short_itm  # |delta| ~ N(d2) proxy for 0DTE screening
        if short_delta > MAX_SHORT_DELTA:
            return

        max_loss_per = (width - credit) * 100.0
        contracts = _size_contracts(max_loss_per, account_size, risk_per_trade_pct)
        max_profit_usd = credit * 100.0 * contracts
        max_loss_usd = max_loss_per * contracts
        reward_risk = credit / (width - credit) if (width - credit) > 0 else 0.0
        ev_per = pop * (credit * 100.0) - (1 - pop) * max_loss_per
        ev_usd = ev_per * contracts

        if stype == "put_credit":
            breakeven = ks - credit
        else:
            breakeven = ks + credit

        # Score: reward POP and positive EV, lightly favor tighter widths and
        # richer credit-to-width. POP dominates so the safest spreads rank first.
        score = (pop * 100.0
                 + (ev_per / max(width, 1.0))
                 + (credit / width) * 10.0)

        results.append(CreditSpread(
            underlying=underlying,
            spread_type=stype,
            expiration=expiration,
            underlying_price=spot,
            short_strike=ks,
            long_strike=kl,
            width=width,
            credit=credit,
            max_profit_usd=max_profit_usd,
            max_loss_usd=max_loss_usd,
            contracts=contracts,
            reference_iv=reference_iv,
            short_delta=short_delta,
            pop=pop,
            expected_value_usd=ev_usd,
            breakeven=breakeven,
            minutes_to_expiry=minutes_to_expiry,
            reward_risk=reward_risk,
            score=score,
            short_symbol=str(short_row.get("contractSymbol", "")),
            long_symbol=str(long_row.get("contractSymbol", "")),
        ))

    # Put credit spreads: short strike BELOW spot, long strike further below.
    put_rows = [r for r in _clean_rows(puts) if r["_strike"] < spot]
    for i, short_row in enumerate(put_rows):
        for long_row in put_rows[:i]:  # strictly lower strike = further OTM
            _consider(short_row, long_row, "put", "put_credit")

    # Call credit spreads: short strike ABOVE spot, long strike further above.
    call_rows = [r for r in _clean_rows(calls) if r["_strike"] > spot]
    for i, short_row in enumerate(call_rows):
        for long_row in call_rows[i + 1:]:  # strictly higher strike = further OTM
            _consider(short_row, long_row, "call", "call_credit")

    results.sort(key=lambda s: s.score, reverse=True)
    return results[:max_results]


@dataclass
class SpreadTrade:
    """A settled credit spread with realized P&L (for the backtester)."""
    date: str
    underlying: str
    spread_type: str
    short_strike: float
    long_strike: float
    width: float
    credit: float
    contracts: int
    pop: float
    entry_underlying: float
    exit_underlying: float
    exit_reason: str          # 'expired_worthless' | 'profit_target' | 'stop' | 'expiry_loss'
    gross_pnl_usd: float
    commission_usd: float
    pnl_usd: float
    max_profit_usd: float
    max_loss_usd: float


def _spread_value(spot: float, short_k: float, long_k: float, otype: str,
                  T: float, sigma: float, r: float) -> float:
    """Current per-share cost to CLOSE the spread (buy back short, sell long)."""
    short_v = bs_price(spot, short_k, T, r, max(sigma, 1e-6), otype)
    long_v = bs_price(spot, long_k, T, r, max(sigma, 1e-6), otype)
    return short_v - long_v  # what we'd pay to close (positive = still owe)


def settle_spread(
    spread: CreditSpread,
    path,
    *,
    date: str,
    risk_free: float = 0.045,
    profit_target_frac: float = 0.55,
    stop_multiple: float = 2.0,
    commission_per_contract: float = 0.65,
) -> SpreadTrade:
    """Simulate a 0DTE credit spread over an intraday underlying ``path``.

    Management rules (standard for premium selling):
      * **Profit target** — buy back once we can keep ``profit_target_frac`` of
        the credit (i.e. the spread's close cost falls to (1-frac)*credit).
      * **Stop** — bail if the close cost reaches ``stop_multiple`` × credit
        (a 2× stop caps the loss well inside the defined max).
      * **Expiry** — whatever's left settles at intrinsic: full credit kept if
        OTM, else (intrinsic − credit) loss, floored at the defined max loss.
    """
    otype = "put" if spread.spread_type == "put_credit" else "call"
    ks, kl = spread.short_strike, spread.long_strike
    width = spread.width
    credit = spread.credit
    contracts = spread.contracts
    sigma = spread.reference_iv
    minutes = spread.minutes_to_expiry
    T0 = max(minutes, 1) / (60 * 24 * 365)
    mult = 100.0 * contracts

    n = max(len(path) - 1, 1)
    target_close = (1.0 - profit_target_frac) * credit  # cost to close at target
    stop_close = min(stop_multiple * credit, width)      # cost to close at stop

    exit_reason = "expiry"
    per_share_pnl: float | None = None
    exit_underlying = float(path[-1])

    for k in range(1, n):
        frac = k / n
        S_k = float(path[k])
        T_k = T0 * (1.0 - frac)
        close_cost = _spread_value(S_k, ks, kl, otype, T_k, sigma, risk_free)
        close_cost = max(close_cost, 0.0)
        if close_cost <= target_close:
            per_share_pnl = credit - close_cost
            exit_reason = "profit_target"
            exit_underlying = S_k
            break
        if close_cost >= stop_close:
            per_share_pnl = credit - min(close_cost, width)
            exit_reason = "stop"
            exit_underlying = S_k
            break

    if per_share_pnl is None:
        # Settle at expiry intrinsic.
        S_T = float(path[-1])
        if otype == "put":
            short_intrinsic = max(ks - S_T, 0.0)
            long_intrinsic = max(kl - S_T, 0.0)
        else:
            short_intrinsic = max(S_T - ks, 0.0)
            long_intrinsic = max(S_T - kl, 0.0)
        close_cost = min(max(short_intrinsic - long_intrinsic, 0.0), width)
        per_share_pnl = credit - close_cost
        exit_reason = "expired_worthless" if close_cost <= 1e-9 else "expiry_loss"
        exit_underlying = S_T

    gross = per_share_pnl * mult
    commission = commission_per_contract * contracts * 2.0 * 2.0  # 2 legs, in+out
    pnl = gross - commission
    return SpreadTrade(
        date=date,
        underlying=spread.underlying,
        spread_type=spread.spread_type,
        short_strike=ks,
        long_strike=kl,
        width=width,
        credit=credit,
        contracts=contracts,
        pop=spread.pop,
        entry_underlying=spread.underlying_price,
        exit_underlying=exit_underlying,
        exit_reason=exit_reason,
        gross_pnl_usd=round(gross, 2),
        commission_usd=round(commission, 2),
        pnl_usd=round(pnl, 2),
        max_profit_usd=spread.max_profit_usd,
        max_loss_usd=spread.max_loss_usd,
    )


