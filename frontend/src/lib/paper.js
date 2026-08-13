// Virtual paper-trading engine. Everything is educational and lives in
// localStorage — no brokerage, no real orders, no money. It tracks virtual cash,
// open 0DTE option positions, and a closed-trade log, and marks open positions
// to a live/synthetic price so the Practice tab can show real-time P&L.
//
// A "position" is a long option (buy-to-open). Worst case is a 100% loss of
// premium, matching how the scanner's trade plans are sized.

import { bsPrice } from './pricing.js';

const LS_KEY = 'zdte.paper';
export const STARTING_CASH = 10_000;
const CONTRACT_MULTIPLIER = 100;
export const COMMISSION_PER_CONTRACT = 0.65;

function blankState() {
  return {
    cash: STARTING_CASH,
    startingCash: STARTING_CASH,
    positions: [], // open
    history: [],   // closed trades
    createdAt: new Date().toISOString(),
  };
}

export function loadPaper() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return blankState();
    const s = JSON.parse(raw);
    if (!s || typeof s.cash !== 'number') return blankState();
    s.positions = Array.isArray(s.positions) ? s.positions : [];
    s.history = Array.isArray(s.history) ? s.history : [];
    if (typeof s.startingCash !== 'number') s.startingCash = STARTING_CASH;
    return s;
  } catch {
    return blankState();
  }
}

export function savePaper(state) {
  try { localStorage.setItem(LS_KEY, JSON.stringify(state)); } catch { /* ignore */ }
}

export function resetPaper() {
  const s = blankState();
  savePaper(s);
  return s;
}

let _seq = 0;
function nextId() {
  _seq += 1;
  return `pt-${Date.now()}-${_seq}`;
}

/**
 * Buy-to-open a contract. `contract` should carry:
 *   { symbol, underlying, option_type, strike, expiration, ask, mid,
 *     reference_iv, minutes_to_expiry, underlying_price }
 * Returns { ok, state, error }.
 */
export function buyToOpen(state, contract, contracts, { price } = {}) {
  const qty = Math.max(1, Math.trunc(contracts || 1));
  const fill = Number(price ?? contract.ask ?? contract.mid ?? 0);
  if (!(fill > 0)) return { ok: false, state, error: 'No valid fill price for this contract.' };
  const cost = fill * CONTRACT_MULTIPLIER * qty;
  const commission = COMMISSION_PER_CONTRACT * qty;
  const total = cost + commission;
  if (total > state.cash) {
    return { ok: false, state, error: `Not enough virtual cash (need $${total.toFixed(2)}, have $${state.cash.toFixed(2)}).` };
  }
  const pos = {
    id: nextId(),
    symbol: contract.symbol,
    underlying: contract.underlying,
    optionType: contract.option_type,
    strike: contract.strike,
    expiration: contract.expiration,
    entryPrice: fill,
    contracts: qty,
    entryTime: new Date().toISOString(),
    referenceIv: contract.reference_iv ?? null,
    entryUnderlying: contract.underlying_price ?? null,
    minutesToExpiryAtEntry: contract.minutes_to_expiry ?? null,
    commissionPaid: commission,
  };
  const next = {
    ...state,
    cash: state.cash - total,
    positions: [...state.positions, pos],
  };
  savePaper(next);
  return { ok: true, state: next };
}

/**
 * Sell-to-close an open position at `price` (defaults to the position's last
 * marked value). Records realized P&L in history. Returns { ok, state, trade }.
 */
export function sellToClose(state, positionId, price) {
  const pos = state.positions.find((p) => p.id === positionId);
  if (!pos) return { ok: false, state, error: 'Position not found.' };
  const exit = Number(price);
  const exitPrice = exit >= 0 ? exit : 0;
  const commission = COMMISSION_PER_CONTRACT * pos.contracts;
  const proceeds = exitPrice * CONTRACT_MULTIPLIER * pos.contracts - commission;
  const costBasis = pos.entryPrice * CONTRACT_MULTIPLIER * pos.contracts;
  const realized = proceeds - costBasis; // net of exit commission (entry commission already paid)
  const trade = {
    ...pos,
    exitPrice,
    exitTime: new Date().toISOString(),
    realizedPnl: realized,
    exitCommission: commission,
    returnPct: costBasis > 0 ? realized / costBasis : 0,
  };
  const next = {
    ...state,
    cash: state.cash + proceeds,
    positions: state.positions.filter((p) => p.id !== positionId),
    history: [trade, ...state.history],
  };
  savePaper(next);
  return { ok: true, state: next, trade };
}

/**
 * Mark an open position to a current option price. If `quote` (a live/synthetic
 * option price) is supplied, use it; otherwise reprice with Black-Scholes using
 * the current underlying spot, the entry reference IV, and time decayed to
 * `minutesLeft`. Returns { markPrice, value, unrealizedPnl, unrealizedPct }.
 */
export function markPosition(pos, { spot, minutesLeft, quote } = {}) {
  let mark = quote;
  if (!(mark >= 0) && spot > 0 && pos.referenceIv) {
    const minutes = Math.max(Number(minutesLeft ?? pos.minutesToExpiryAtEntry ?? 1), 0);
    const T = Math.max(minutes, 0.0001) / (60 * 24 * 365);
    mark = bsPrice(spot, pos.strike, T, 0.045, pos.referenceIv, pos.optionType);
  }
  if (!(mark >= 0)) mark = pos.entryPrice; // fall back to flat
  const value = mark * CONTRACT_MULTIPLIER * pos.contracts;
  const cost = pos.entryPrice * CONTRACT_MULTIPLIER * pos.contracts;
  const unrealizedPnl = value - cost;
  return {
    markPrice: mark,
    value,
    unrealizedPnl,
    unrealizedPct: cost > 0 ? unrealizedPnl / cost : 0,
  };
}

/** Aggregate account metrics from closed history. */
export function summarize(state) {
  const closed = state.history || [];
  const wins = closed.filter((t) => t.realizedPnl > 0);
  const losses = closed.filter((t) => t.realizedPnl < 0);
  const grossWin = wins.reduce((a, t) => a + t.realizedPnl, 0);
  const grossLoss = Math.abs(losses.reduce((a, t) => a + t.realizedPnl, 0));
  const realized = closed.reduce((a, t) => a + t.realizedPnl, 0);
  return {
    trades: closed.length,
    winRate: closed.length ? wins.length / closed.length : 0,
    realizedPnl: realized,
    profitFactor: grossLoss > 0 ? grossWin / grossLoss : null,
    avgWin: wins.length ? grossWin / wins.length : 0,
    avgLoss: losses.length ? grossLoss / losses.length : 0,
  };
}
