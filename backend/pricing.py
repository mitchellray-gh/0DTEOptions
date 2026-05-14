"""Black-Scholes pricing, implied volatility, and Greeks.

All functions assume European-style options. SPY/QQQ/etc. weekly options are
American but for short-dated, near-the-money, non-dividend-adjusted contracts
the Black-Scholes value is a very close approximation that is well-suited for
ranking relative mispricings — which is what this scanner does.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.stats import norm

SQRT_2PI = math.sqrt(2.0 * math.pi)


@dataclass
class Greeks:
    delta: float
    gamma: float
    vega: float       # per 1.00 change in vol (i.e. 100%); divide by 100 for per-1-vol-pt
    theta: float      # per year; divide by 365 for per-day
    rho: float


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0):
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return None, None
    vt = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / vt
    d2 = d1 - vt
    return d1, d2


def bs_price(S: float, K: float, T: float, r: float, sigma: float,
             option_type: str, q: float = 0.0) -> float:
    """Black-Scholes-Merton price for a European call or put.

    Args:
        S: spot price
        K: strike
        T: time to expiry in years
        r: risk-free rate (annualized, decimal)
        sigma: volatility (annualized, decimal)
        option_type: "call" or "put"
        q: continuous dividend yield (annualized, decimal)
    """
    if T <= 0:
        # at expiry — payoff
        if option_type == "call":
            return max(S - K, 0.0)
        return max(K - S, 0.0)
    if sigma <= 0:
        # discounted intrinsic
        fwd = S * math.exp(-q * T) - K * math.exp(-r * T)
        if option_type == "call":
            return max(fwd, 0.0)
        return max(-fwd, 0.0)

    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    disc_r = math.exp(-r * T)
    disc_q = math.exp(-q * T)
    if option_type == "call":
        return S * disc_q * norm.cdf(d1) - K * disc_r * norm.cdf(d2)
    return K * disc_r * norm.cdf(-d2) - S * disc_q * norm.cdf(-d1)


def bs_greeks(S: float, K: float, T: float, r: float, sigma: float,
              option_type: str, q: float = 0.0) -> Greeks:
    """Black-Scholes Greeks."""
    if T <= 0 or sigma <= 0:
        return Greeks(0.0, 0.0, 0.0, 0.0, 0.0)

    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    disc_r = math.exp(-r * T)
    disc_q = math.exp(-q * T)
    pdf_d1 = math.exp(-0.5 * d1 * d1) / SQRT_2PI

    gamma = disc_q * pdf_d1 / (S * sigma * math.sqrt(T))
    vega = S * disc_q * pdf_d1 * math.sqrt(T)
    if option_type == "call":
        delta = disc_q * norm.cdf(d1)
        theta = (-(S * disc_q * pdf_d1 * sigma) / (2 * math.sqrt(T))
                 - r * K * disc_r * norm.cdf(d2)
                 + q * S * disc_q * norm.cdf(d1))
        rho = K * T * disc_r * norm.cdf(d2)
    else:
        delta = -disc_q * norm.cdf(-d1)
        theta = (-(S * disc_q * pdf_d1 * sigma) / (2 * math.sqrt(T))
                 + r * K * disc_r * norm.cdf(-d2)
                 - q * S * disc_q * norm.cdf(-d1))
        rho = -K * T * disc_r * norm.cdf(-d2)

    return Greeks(delta=delta, gamma=gamma, vega=vega, theta=theta, rho=rho)


def implied_vol(market_price: float, S: float, K: float, T: float, r: float,
                option_type: str, q: float = 0.0,
                tol: float = 1e-5, max_iter: int = 100) -> float | None:
    """Solve for IV using Brent's method on a bracketed root.

    Returns None if no solution can be bracketed (e.g. market price below
    intrinsic value, or no liquidity).
    """
    if market_price is None or market_price <= 0 or T <= 0:
        return None

    # Intrinsic floor sanity check
    intrinsic = bs_price(S, K, T, r, 1e-9, option_type, q)
    if market_price < intrinsic - 1e-6:
        return None

    lo, hi = 1e-4, 5.0  # 0.01% to 500% vol — generous bracket
    f_lo = bs_price(S, K, T, r, lo, option_type, q) - market_price
    f_hi = bs_price(S, K, T, r, hi, option_type, q) - market_price
    if f_lo * f_hi > 0:
        return None

    # Brent's method
    a, b = lo, hi
    fa, fb = f_lo, f_hi
    if abs(fa) < abs(fb):
        a, b = b, a
        fa, fb = fb, fa
    c, fc = a, fa
    mflag = True
    s = b
    for _ in range(max_iter):
        if abs(fb) < tol:
            return b
        if fa != fc and fb != fc:
            s = (a * fb * fc / ((fa - fb) * (fa - fc))
                 + b * fa * fc / ((fb - fa) * (fb - fc))
                 + c * fa * fb / ((fc - fa) * (fc - fb)))
        else:
            s = b - fb * (b - a) / (fb - fa)
        cond1 = not ((3 * a + b) / 4 < s < b or b < s < (3 * a + b) / 4)
        cond2 = mflag and abs(s - b) >= abs(b - c) / 2
        cond3 = (not mflag) and abs(s - b) >= abs(c - a) / 2
        if cond1 or cond2 or cond3:
            s = (a + b) / 2
            mflag = True
        else:
            mflag = False
        fs = bs_price(S, K, T, r, s, option_type, q) - market_price
        c, fc = b, fb
        if fa * fs < 0:
            b, fb = s, fs
        else:
            a, fa = s, fs
        if abs(fa) < abs(fb):
            a, b = b, a
            fa, fb = fb, fa
    return b
