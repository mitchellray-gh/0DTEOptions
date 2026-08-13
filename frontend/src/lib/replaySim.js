// Synthetic 0DTE option-chain generator for the historical-replay practice mode.
//
// HONESTY: real historical *option* quotes aren't freely available. Replay uses
// REAL underlying prices (from yfinance intraday bars) but builds SYNTHETIC
// chains around each price — Black-Scholes value at a base IV, plus a volatility
// smile and small per-strike noise so the scanner has realistic mispricings to
// flag. This mirrors backend/backtest/simulator.py and is for practice only.

import { bsPrice } from './pricing.js';

const RISK_FREE = 0.045;

// Deterministic PRNG (mulberry32) so a given (date, minute) replays identically.
function mulberry32(seed) {
  let a = seed >>> 0;
  return function rand() {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hashStr(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i += 1) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function roundStrikeStep(spot) {
  if (spot >= 400) return 5;
  if (spot >= 100) return 1;
  if (spot >= 25) return 0.5;
  return 0.5;
}

/**
 * Build a synthetic chain around `spot` with `minutesLeft` to expiry.
 * @returns { underlying, spot, expiration, minutes_to_expiry, calls, puts }
 */
export function buildSyntheticChain(underlying, spot, minutesLeft, {
  baseIv = 0.20,
  seed = 1,
  expiration,
} = {}) {
  const rand = mulberry32(seed ^ hashStr(`${underlying}:${Math.round(spot * 100)}:${minutesLeft}`));
  const step = roundStrikeStep(spot);
  const atm = Math.round(spot / step) * step;
  const minutes = Math.max(minutesLeft, 1);
  const T = minutes / (60 * 24 * 365);
  const exp = expiration || new Date().toISOString().slice(0, 10);

  const mkRow = (strike, type) => {
    const moneyness = (strike - spot) / spot;
    // Simple smile: OTM wings priced with a touch more IV.
    const smile = 1 + 1.2 * moneyness * moneyness;
    const noise = 1 + (rand() - 0.5) * 0.14; // ±7% IV dispersion → mispricings
    const iv = Math.max(baseIv * smile * noise, 0.03);
    const fair = bsPrice(spot, strike, T, RISK_FREE, iv, type);
    const mid = Math.max(fair, 0.01);
    // Spread scales with how far from ATM (illiquid wings = wider).
    const relSpread = 0.04 + Math.min(Math.abs(moneyness) * 0.6, 0.2);
    const half = (mid * relSpread) / 2;
    const bid = Math.max(mid - half, 0);
    const ask = mid + half;
    const dist = Math.abs(moneyness);
    const liq = Math.max(0, 1 - dist * 8);
    const volume = Math.round(50 + liq * 4000 * rand());
    const oi = Math.round(100 + liq * 9000 * rand());
    return {
      contractSymbol: `${underlying}${exp.replace(/-/g, '')}${type === 'call' ? 'C' : 'P'}${String(Math.round(strike * 1000)).padStart(8, '0')}`,
      strike,
      bid: Number(bid.toFixed(2)),
      ask: Number(ask.toFixed(2)),
      lastPrice: Number(mid.toFixed(2)),
      volume,
      openInterest: oi,
      impliedVolatility: Number(iv.toFixed(4)),
    };
  };

  const calls = [];
  const puts = [];
  for (let i = -8; i <= 8; i += 1) {
    const strike = Number((atm + i * step).toFixed(2));
    if (strike <= 0) continue;
    calls.push(mkRow(strike, 'call'));
    puts.push(mkRow(strike, 'put'));
  }
  return {
    underlying,
    spot: Number(spot.toFixed(2)),
    expiration: exp,
    minutes_to_expiry: Math.round(minutes),
    calls,
    puts,
  };
}
