// 0DTE scanner — a JavaScript port of backend/scanner.py. Takes the raw option
// chains returned by the thin Python proxy (/api/chain) and runs the full
// pipeline in the browser: reference-IV anchor, per-contract evaluation,
// scoring, trade plan, and beginner coaching. The output matches the shape the
// React components already consume (results / notes / rejection_summary).

import { bsGreeks, bsPrice, impliedVol } from './pricing.js';
import { fmt$, fmtPct as fmtPct1, fmtPct0 } from './format.js';

// Tunable quality filters — kept in sync with backend/scanner.py.
export const MIN_VOLUME = 50;
export const MIN_OPEN_INTEREST = 100;
export const MIN_BID = 0.05;
export const MAX_REL_SPREAD = 0.25; // (ask-bid)/mid
export const MAX_STRIKE_DISTANCE_PCT = 0.5; // reject strikes >50% from spot
export const NEAR_THE_MONEY_PCT = 0.03; // ±3% for the reference-IV calc
export const DEFAULT_RISK_FREE_RATE = 0.045;
const YEAR_MINUTES = 60 * 24 * 365;

const num = (v, d = 0) => {
  const n = Number(v);
  return Number.isFinite(n) ? n : d;
};
// Round on the true stored value (like Python's round) instead of scaling by
// 10**n first, which can re-introduce an exact .5 and flip the last cent.
const round = (x, n = 4) => Number(Number(x).toFixed(n));

function safeMid(bid, ask, last) {
  if (bid > 0 && ask > 0 && ask >= bid) return (bid + ask) / 2;
  if (last > 0) return last;
  return Math.max(bid, ask, 0);
}

/**
 * Chain consensus IV: volume-weighted IV of near-the-money contracts, falling
 * back to the whole-chain median, or null if no usable IVs exist.
 */
export function computeReferenceIv(calls, puts, spot) {
  const lo = spot * (1 - NEAR_THE_MONEY_PCT);
  const hi = spot * (1 + NEAR_THE_MONEY_PCT);
  const all = [...calls, ...puts];

  const near = all.filter((r) => {
    const k = num(r.strike);
    const iv = num(r.impliedVolatility);
    const vol = num(r.volume);
    return k >= lo && k <= hi && iv > 0.01 && iv < 5 && vol > 0;
  });

  if (near.length) {
    let wsum = 0;
    let w = 0;
    for (const r of near) {
      const weight = Math.max(num(r.volume), 1);
      wsum += num(r.impliedVolatility) * weight;
      w += weight;
    }
    return w > 0 ? wsum / w : null;
  }

  // Fallback: median IV across the whole chain.
  const ivs = all
    .map((r) => num(r.impliedVolatility))
    .filter((iv) => iv > 0.01 && iv < 5)
    .sort((a, b) => a - b);
  if (!ivs.length) return null;
  const m = Math.floor(ivs.length / 2);
  return ivs.length % 2 ? ivs[m] : (ivs[m - 1] + ivs[m]) / 2;
}

function evaluateContract(row, optionType, ctx, riskFree) {
  const bid = num(row.bid);
  const ask = num(row.ask);
  const last = num(row.lastPrice);
  const volume = Math.trunc(num(row.volume));
  const oi = Math.trunc(num(row.openInterest));
  const strike = num(row.strike);
  const symbol = String(row.contractSymbol || '');

  const reject = (reason, detail) => ({
    kind: 'rej',
    rejected: {
      symbol,
      underlying: ctx.underlying,
      strike,
      option_type: optionType,
      bid: round(bid, 4),
      ask: round(ask, 4),
      volume,
      open_interest: oi,
      rejection_reason: reason,
      rejection_detail: detail,
    },
  });

  const strikeDistance = Math.abs(strike - ctx.spot) / Math.max(ctx.spot, 0.01);
  if (strikeDistance > MAX_STRIKE_DISTANCE_PCT) {
    return reject(
      'non_standard_strike',
      `Strike ${fmt$(strike)} is ${fmtPct0(strikeDistance)} from spot ${fmt$(ctx.spot)} — exceeds 50% limit.`
    );
  }
  if (bid < MIN_BID || ask <= 0) {
    return reject('low_bid_ask', `Bid ${fmt$(bid)} < min $0.05 or ask ${fmt$(ask)} ≤ 0.`);
  }
  if (volume < MIN_VOLUME || oi < MIN_OPEN_INTEREST) {
    return reject(
      'low_liquidity',
      `Volume ${volume.toLocaleString()} < ${MIN_VOLUME} or OI ${oi.toLocaleString()} < ${MIN_OPEN_INTEREST}.`
    );
  }
  const mid = safeMid(bid, ask, last);
  if (mid <= 0) {
    return reject('no_valid_mid', 'Could not compute a valid midpoint price.');
  }
  const relSpread = mid > 0 ? (ask - bid) / mid : 1;
  if (relSpread > MAX_REL_SPREAD) {
    return reject(
      'wide_spread',
      `Relative spread ${fmtPct1(relSpread)} > max 25% (bid ${fmt$(bid)}, ask ${fmt$(ask)}, mid ${fmt$(mid)}).`
    );
  }

  const fair = bsPrice(ctx.spot, strike, ctx.T, riskFree, ctx.referenceIv, optionType);
  const edgeAbs = fair - ask;
  if (edgeAbs <= 0) {
    return reject('no_edge', `Fair value ${fmt$(fair)} ≤ ask ${fmt$(ask)} — no positive edge.`);
  }
  const edgePct = edgeAbs / ask;
  if (edgePct < 0.05) {
    return reject(
      'insufficient_edge',
      `Edge ${fmtPct1(edgePct)} < 5% minimum (fair ${fmt$(fair)} vs ask ${fmt$(ask)}).`
    );
  }

  const marketIv = impliedVol(mid, ctx.spot, strike, ctx.T, riskFree, optionType);
  const g = bsGreeks(ctx.spot, strike, ctx.T, riskFree, ctx.referenceIv, optionType);

  const liqScore = Math.log10(Math.max(volume, 1) + Math.max(oi, 1));
  const atmScore = 1 / (1 + Math.abs(strike - ctx.spot) / Math.max(ctx.spot * 0.01, 1e-6));
  const score = edgePct * 100 + liqScore + atmScore;

  return {
    kind: 'opp',
    opportunity: {
      symbol,
      underlying: ctx.underlying,
      underlying_price: round(ctx.spot, 4),
      expiration: ctx.expiry,
      strike,
      option_type: optionType,
      bid: round(bid, 4),
      ask: round(ask, 4),
      mid: round(mid, 4),
      last: round(last, 4),
      volume,
      open_interest: oi,
      market_iv: marketIv != null ? round(marketIv, 4) : null,
      reference_iv: round(ctx.referenceIv, 4),
      fair_value: round(fair, 4),
      edge_abs: round(edgeAbs, 4),
      edge_pct: round(edgePct, 4),
      delta: round(g.delta, 4),
      gamma: round(g.gamma, 6),
      theta_per_day: round(g.theta / 365, 4),
      vega_per_volpt: round(g.vega / 100, 4),
      minutes_to_expiry: ctx.minutes,
      score: round(score, 3),
    },
  };
}

function buildPlan(opp, accountSize = 5000, riskPct = 0.02) {
  const costPerContract = opp.ask * 100;
  const riskBudget = accountSize * riskPct;
  const contracts = Math.max(Math.floor(riskBudget / Math.max(costPerContract, 0.01)), 1);
  const totalCost = contracts * costPerContract;

  const targetExit = opp.ask + (opp.fair_value - opp.ask) * 0.5;
  const targetProfit = (targetExit - opp.ask) * 100 * contracts;
  const stopPrice = opp.ask * 0.5;
  const stopLossUsd = (opp.ask - stopPrice) * 100 * contracts;

  let breakeven;
  let sideHuman;
  if (opp.option_type === 'call') {
    breakeven = opp.strike + opp.ask;
    sideHuman = `BUY ${contracts} ${opp.underlying} ${opp.expiration} $${opp.strike} CALL`;
  } else {
    breakeven = opp.strike - opp.ask;
    sideHuman = `BUY ${contracts} ${opp.underlying} ${opp.expiration} $${opp.strike} PUT`;
  }

  const rationale =
    `Black-Scholes fair value at the chain's volume-weighted IV ` +
    `(${fmtPct1(opp.reference_iv)}) is ${fmt$(opp.fair_value)}, but the contract is offered ` +
    `at ${fmt$(opp.ask)} — an edge of ${fmtPct1(opp.edge_pct)} (${fmt$(opp.edge_abs)}/share). ` +
    `With ${opp.minutes_to_expiry} minutes to expiry, delta is ${opp.delta.toFixed(2)} ` +
    `and theta is ${fmt$(opp.theta_per_day)}/day.`;

  const steps = [
    `1. In your broker, open the options chain for ${opp.underlying} expiring ${opp.expiration}.`,
    `2. Select the $${opp.strike} ${opp.option_type.toUpperCase()} contract (${opp.symbol}).`,
    `3. Place a LIMIT BUY-TO-OPEN order for ${contracts} ${opp.option_type.toUpperCase()} contract(s) at ${fmt$(opp.ask)} or better.`,
    `4. Immediately stage a LIMIT SELL-TO-CLOSE order on the same ${opp.option_type.toUpperCase()} at ${fmt$(targetExit)} (take-profit).`,
    `5. Set a stop at ${fmt$(stopPrice)} (≈50% of premium); SELL-TO-CLOSE manually if hit.`,
    `6. SELL-TO-CLOSE any remaining position by 15:45 ET to avoid pin / assignment risk.`,
  ];

  return {
    action: 'BUY_TO_OPEN',
    contract_symbol: opp.symbol,
    side_human: sideHuman,
    limit_price: round(opp.ask, 2),
    suggested_contracts: contracts,
    cost_per_contract_usd: round(costPerContract, 2),
    total_cost_usd: round(totalCost, 2),
    max_loss_usd: round(totalCost, 2),
    breakeven_underlying_price: round(breakeven, 2),
    target_exit_price: round(targetExit, 2),
    target_profit_usd: round(targetProfit, 2),
    stop_loss_price: round(stopPrice, 2),
    stop_loss_usd: round(stopLossUsd, 2),
    rationale,
    steps,
  };
}

function buildCoaching(opp, plan) {
  const otype = opp.option_type.toUpperCase();
  const direction = opp.option_type === 'call' ? 'up' : 'down';

  const action_summary = `BUY TO OPEN ${otype} @ ${fmt$(opp.ask)}`;
  const why =
    `Our model says this ${otype} is worth ${fmt$(opp.fair_value)} but the market is selling it ` +
    `for only ${fmt$(opp.ask)} — that's ${fmtPct0(opp.edge_pct)} cheaper than fair value. ` +
    `Think of it like finding a $100 item on sale for $${(100 * (1 - opp.edge_pct)).toFixed(0)}.`;
  const entry_instruction =
    `In your broker, search for ${opp.underlying} options expiring ${opp.expiration}. ` +
    `Find the $${opp.strike} ${otype} strike. Place a LIMIT order (not market!) to BUY TO OPEN the ${otype} at ` +
    `${fmt$(opp.ask)} or lower. You'll buy ${plan.suggested_contracts} contract(s) for a total of ` +
    `${fmt$(plan.total_cost_usd)} (${plan.suggested_contracts} × ${fmt$(plan.cost_per_contract_usd)}).`;
  const expected_profit =
    `If ${opp.underlying} moves ${direction} and the option price reaches ${fmt$(plan.target_exit_price)} ` +
    `(our conservative target), you'd make ${fmt$(plan.target_profit_usd)} profit — that's a ` +
    `${((plan.target_profit_usd / plan.total_cost_usd) * 100).toFixed(0)}% return on your ` +
    `${fmt$(plan.total_cost_usd)} investment.`;
  const max_risk =
    `The MOST you can lose is ${fmt$(plan.max_loss_usd)} (your entire premium). This happens if ` +
    `${opp.underlying} finishes ${opp.option_type === 'call' ? 'below' : 'above'} $${opp.strike} ` +
    `at expiration. Never risk more than you can afford to lose.`;

  let timeNote;
  if (opp.minutes_to_expiry <= 30) {
    timeNote = `⚠️ ONLY ${opp.minutes_to_expiry} MINUTES LEFT — this trade needs immediate attention. Set your sell order right away.`;
  } else if (opp.minutes_to_expiry <= 120) {
    timeNote = `You have about ${opp.minutes_to_expiry} minutes until market close. Watch this closely and don't walk away.`;
  } else {
    const hrs = Math.floor(opp.minutes_to_expiry / 60);
    const mins = opp.minutes_to_expiry % 60;
    timeNote = `You have roughly ${hrs}h ${mins}m until market close. Check in every 15-30 minutes.`;
  }
  const exit_plan =
    `As soon as your BUY TO OPEN order fills, place a LIMIT SELL TO CLOSE order on the same ` +
    `${otype} at ${fmt$(plan.target_exit_price)} (take-profit). If the option drops to ` +
    `${fmt$(plan.stop_loss_price)} (half your cost), SELL TO CLOSE to cut your losses. ` +
    `${timeNote} SELL TO CLOSE all positions by 3:45 PM ET no matter what — holding past ` +
    `that risks automatic exercise and unexpected assignment.`;

  const watch_list = [
    Math.abs(opp.delta) < 0.5
      ? `📈 ${opp.underlying} stock price — you need it to move ${direction} toward $${opp.strike}`
      : `📈 ${opp.underlying} stock price — it's already near your strike, keep it moving ${direction}`,
    `💰 Option bid price — SELL TO CLOSE when it hits ${fmt$(plan.target_exit_price)} or higher`,
    `🛑 SELL TO CLOSE to cut losses if option price drops to ${fmt$(plan.stop_loss_price)}`,
    `⏰ Time decay is your enemy — this ${otype} loses ${fmt$(Math.abs(opp.theta_per_day))}/day (accelerating)`,
    `📊 Volume: ${opp.volume.toLocaleString()} traded today — ${opp.volume >= 200 ? 'good liquidity' : 'decent liquidity, watch bid-ask spread'}`,
  ];

  let urgency;
  if (opp.minutes_to_expiry <= 60) urgency = 'high';
  else if (opp.minutes_to_expiry <= 180) urgency = 'medium';
  else urgency = 'low';

  let confidence;
  if (opp.edge_pct >= 0.15 && opp.score >= 15) confidence = 'strong';
  else if (opp.edge_pct >= 0.08 || opp.score >= 10) confidence = 'moderate';
  else confidence = 'speculative';

  return {
    action_summary,
    why,
    entry_instruction,
    expected_profit,
    max_risk,
    exit_plan,
    watch_list,
    urgency,
    confidence,
  };
}

/**
 * Run the full scan over raw chains from /api/chain.
 * @param {Array} chains  [{ underlying, spot, expiration, minutes_to_expiry, calls, puts }]
 * @param {Object} opts   { riskFree, accountSize, riskPct, maxResults }
 * @returns scan-result object the components consume (results / notes / rejection_summary).
 */
export function scanChains(chains, opts = {}) {
  const riskFree = opts.riskFree ?? DEFAULT_RISK_FREE_RATE;
  const accountSize = opts.accountSize ?? 5000;
  const riskPct = opts.riskPct ?? 0.02;
  const maxResults = opts.maxResults ?? 50;

  const opportunities = [];
  const rejections = [];
  const notes = [];
  let totalScanned = 0;

  for (const chain of chains || []) {
    const calls = chain.calls || [];
    const puts = chain.puts || [];
    if (!calls.length && !puts.length) {
      notes.push(`${chain.underlying}: empty chain`);
      continue;
    }
    const spot = num(chain.spot);
    const referenceIv = computeReferenceIv(calls, puts, spot);
    if (referenceIv == null) {
      notes.push(`${chain.underlying}: no usable implied volatilities`);
      continue;
    }
    const minutes = Math.max(Math.trunc(num(chain.minutes_to_expiry, 1)), 1);
    const ctx = {
      underlying: chain.underlying,
      spot,
      expiry: chain.expiration,
      minutes,
      T: minutes / YEAR_MINUTES,
      referenceIv,
    };

    for (const [rows, otype] of [[calls, 'call'], [puts, 'put']]) {
      for (const row of rows) {
        totalScanned += 1;
        const res = evaluateContract(row, otype, ctx, riskFree);
        if (res.kind === 'opp') opportunities.push(res.opportunity);
        else rejections.push(res.rejected);
      }
    }
    notes.push(
      `${chain.underlying}: spot=${fmt$(spot)}, expiry=${chain.expiration}, ` +
        `ref_IV=${fmtPct1(referenceIv)}, mins_left=${minutes}`
    );
  }

  opportunities.sort((a, b) => b.score - a.score);
  const top = opportunities.slice(0, maxResults);

  const results = top.map((o) => {
    const plan = buildPlan(o, accountSize, riskPct);
    return { opportunity: o, plan, coaching: buildCoaching(o, plan) };
  });

  // Rejection summary with up to 5 samples per reason.
  const byReason = {};
  const samplesByReason = {};
  for (const rej of rejections) {
    byReason[rej.rejection_reason] = (byReason[rej.rejection_reason] || 0) + 1;
    const bucket = (samplesByReason[rej.rejection_reason] ||= []);
    if (bucket.length < 5) bucket.push(rej);
  }
  const samples = Object.values(samplesByReason).flat();

  return {
    generated_at: new Date().toISOString(),
    risk_free_rate: riskFree,
    tickers_scanned: (chains || []).map((c) => c.underlying),
    count: results.length,
    results,
    notes,
    rejection_summary: {
      total_contracts_scanned: totalScanned,
      total_rejected: rejections.length,
      total_passed: top.length,
      by_reason: byReason,
      samples,
    },
  };
}
