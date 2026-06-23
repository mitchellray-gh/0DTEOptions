// Black-Scholes pricing, implied volatility, and Greeks — a direct JavaScript
// port of backend/pricing.py so the scanner can run entirely in the browser.
//
// All functions assume European-style options. For short-dated, near-the-money,
// non-dividend contracts (what this scanner targets) that is a close enough
// approximation for ranking relative mispricings.

const SQRT_2PI = Math.sqrt(2.0 * Math.PI);

// Abramowitz & Stegun 7.1.26 — max abs error ~1.5e-7, plenty for 2-decimal
// option quotes. Keeps the normal CDF dependency-free in the browser.
function erf(x) {
  const sign = x < 0 ? -1 : 1;
  const ax = Math.abs(x);
  const t = 1 / (1 + 0.3275911 * ax);
  const y =
    1 -
    ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t +
      0.254829592) *
      t *
      Math.exp(-ax * ax);
  return sign * y;
}

function normCdf(x) {
  return 0.5 * (1 + erf(x / Math.SQRT2));
}

function normPdf(x) {
  return Math.exp(-0.5 * x * x) / SQRT_2PI;
}

function d1d2(S, K, T, r, sigma, q = 0) {
  if (T <= 0 || sigma <= 0 || S <= 0 || K <= 0) return [null, null];
  const vt = sigma * Math.sqrt(T);
  const d1 = (Math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / vt;
  return [d1, d1 - vt];
}

/** Black-Scholes-Merton price for a European call or put. */
export function bsPrice(S, K, T, r, sigma, optionType, q = 0) {
  if (T <= 0) {
    return optionType === 'call' ? Math.max(S - K, 0) : Math.max(K - S, 0);
  }
  if (sigma <= 0) {
    const fwd = S * Math.exp(-q * T) - K * Math.exp(-r * T);
    return optionType === 'call' ? Math.max(fwd, 0) : Math.max(-fwd, 0);
  }
  const [d1, d2] = d1d2(S, K, T, r, sigma, q);
  const discR = Math.exp(-r * T);
  const discQ = Math.exp(-q * T);
  if (optionType === 'call') {
    return S * discQ * normCdf(d1) - K * discR * normCdf(d2);
  }
  return K * discR * normCdf(-d2) - S * discQ * normCdf(-d1);
}

/**
 * Black-Scholes Greeks.
 * Returns { delta, gamma, vega, theta, rho } where vega is per 1.00 vol change
 * and theta is per year (callers divide by 100 / 365 for per-vol-pt / per-day).
 */
export function bsGreeks(S, K, T, r, sigma, optionType, q = 0) {
  if (T <= 0 || sigma <= 0) {
    return { delta: 0, gamma: 0, vega: 0, theta: 0, rho: 0 };
  }
  const [d1, d2] = d1d2(S, K, T, r, sigma, q);
  const discR = Math.exp(-r * T);
  const discQ = Math.exp(-q * T);
  const pdfD1 = normPdf(d1);
  const sqrtT = Math.sqrt(T);

  const gamma = (discQ * pdfD1) / (S * sigma * sqrtT);
  const vega = S * discQ * pdfD1 * sqrtT;
  let delta;
  let theta;
  let rho;
  if (optionType === 'call') {
    delta = discQ * normCdf(d1);
    theta =
      -(S * discQ * pdfD1 * sigma) / (2 * sqrtT) -
      r * K * discR * normCdf(d2) +
      q * S * discQ * normCdf(d1);
    rho = K * T * discR * normCdf(d2);
  } else {
    delta = -discQ * normCdf(-d1);
    theta =
      -(S * discQ * pdfD1 * sigma) / (2 * sqrtT) +
      r * K * discR * normCdf(-d2) -
      q * S * discQ * normCdf(-d1);
    rho = -K * T * discR * normCdf(-d2);
  }
  return { delta, gamma, vega, theta, rho };
}

/**
 * Solve for implied volatility by bisection on a bracketed root.
 * Returns null when no solution can be bracketed (price below intrinsic, no
 * liquidity, etc.). Used for display only, so bisection is plenty.
 */
export function impliedVol(price, S, K, T, r, optionType, q = 0) {
  if (price == null || price <= 0 || T <= 0) return null;

  const intrinsic = bsPrice(S, K, T, r, 1e-9, optionType, q);
  if (price < intrinsic - 1e-6) return null;

  let lo = 1e-4;
  let hi = 5.0;
  let fLo = bsPrice(S, K, T, r, lo, optionType, q) - price;
  let fHi = bsPrice(S, K, T, r, hi, optionType, q) - price;
  if (fLo * fHi > 0) return null;

  for (let i = 0; i < 100; i++) {
    const mid = 0.5 * (lo + hi);
    const fMid = bsPrice(S, K, T, r, mid, optionType, q) - price;
    if (Math.abs(fMid) < 1e-5) return mid;
    if (fLo * fMid < 0) {
      hi = mid;
      fHi = fMid;
    } else {
      lo = mid;
      fLo = fMid;
    }
  }
  return 0.5 * (lo + hi);
}
