// Turn a scanner trade plan into a Robinhood-MCP-ready order — a JavaScript
// port of backend/robinhood.py. The scanner stops at "here is the exact trade";
// this bridges the last mile to execution via Robinhood's hosted trading MCP
// server at https://agent.robinhood.com/mcp/trading.
//
// That endpoint is a remote Model Context Protocol server: an MCP-capable agent
// connects to it (authenticating with the user's own Robinhood account) and the
// server exposes trading tools the agent can call. Because it's driven by
// natural language, the robust interface is a precise instruction string; we
// also emit a normalised order spec for callers that map fields directly.
//
// Nothing here talks to Robinhood or places an order — it only PREPARES the
// instruction for a human (or an explicitly authorised agent) to review and
// submit.

export const ROBINHOOD_MCP_ENDPOINT = 'https://agent.robinhood.com/mcp/trading';

const money = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0).toFixed(2);
const strikeText = (k) => {
  const f = Number(k);
  return Number.isFinite(f) ? `${f}` : String(k);
};

/**
 * Build a Robinhood-MCP order from an { opportunity, plan } scan result.
 * @param {Object} opportunity
 * @param {Object} plan
 * @param {Object} [opts] { timeInForce: 'day' | 'gtc' }
 * @returns {{ endpoint, instruction, entry, exit, disclaimer }}
 */
export function buildRobinhoodOrder(opportunity, plan, opts = {}) {
  const o = opportunity || {};
  const p = plan || {};
  const tif = String(opts.timeInForce || 'day').toLowerCase();

  const underlying = o.underlying || '';
  const optionSymbol = o.symbol || p.contract_symbol || '';
  const optionType = String(o.option_type || '').toLowerCase();
  const expiration = o.expiration || '';
  const strike = o.strike ?? 0;
  const minutes = o.minutes_to_expiry;

  const quantity = Math.max(parseInt(p.suggested_contracts, 10) || 1, 1);
  const limitPrice = Number(p.limit_price ?? o.ask ?? 0);
  const totalCost = Number(p.total_cost_usd ?? 0);
  const maxLoss = Number(p.max_loss_usd ?? 0);
  const targetExit = Number(p.target_exit_price ?? 0);
  const targetProfit = Number(p.target_profit_usd ?? 0);
  const stopPrice = Number(p.stop_loss_price ?? 0);

  const typeWord = optionType.toUpperCase() || 'OPTION';
  const contractHuman = `${underlying} ${expiration} $${strikeText(strike)} ${typeWord}`.trim();

  const entry = {
    underlying_symbol: underlying,
    option_symbol: optionSymbol,
    expiration_date: expiration,
    strike_price: Number(strike),
    option_type: optionType,
    side: 'buy',
    position_effect: 'open',
    order_type: 'limit',
    limit_price: Number(money(limitPrice)),
    quantity,
    time_in_force: tif,
  };

  const takeProfit = {
    ...entry,
    side: 'sell',
    position_effect: 'close',
    limit_price: Number(money(targetExit)),
    note: `Take-profit: sell to close ${quantity} contract(s) at $${money(targetExit)} (≈ $${money(targetProfit)} profit).`,
  };
  const stopLoss = {
    ...entry,
    side: 'sell',
    position_effect: 'close',
    order_type: 'stop',
    stop_price: Number(money(stopPrice)),
    limit_price: null,
    note: `Stop-loss: sell to close if the contract trades down to $${money(stopPrice)} (≈50% of premium).`,
  };

  const minutesClause = Number.isFinite(Number(minutes)) && Number(minutes)
    ? ` Only ~${minutes} minutes remain until expiry, so act promptly.`
    : '';

  const instruction =
    `Using the Robinhood trading MCP server (${ROBINHOOD_MCP_ENDPOINT}), ` +
    `place a BUY-TO-OPEN limit order: buy ${quantity} contract(s) of the ` +
    `${contractHuman} option (${optionSymbol}) at a limit price of ` +
    `$${money(limitPrice)} per share, time-in-force ${tif.toUpperCase()}. ` +
    `This costs about $${money(totalCost)} total and risks at most ` +
    `$${money(maxLoss)}. After the buy fills, place a SELL-TO-CLOSE limit ` +
    `order for the same ${quantity} contract(s) at $${money(targetExit)} ` +
    `(take-profit), and sell to close if the contract falls to ` +
    `$${money(stopPrice)} (stop-loss). Close any remaining position by ` +
    `15:45 ET to avoid pin/assignment risk.${minutesClause} ` +
    `Show me the order details and ask for confirmation before submitting.`;

  return {
    endpoint: ROBINHOOD_MCP_ENDPOINT,
    instruction,
    entry,
    exit: [takeProfit, stopLoss],
    disclaimer:
      'Educational use only. This prepares an order for Robinhood\'s trading ' +
      'MCP server but does not place it. Review every detail and confirm in ' +
      'your account before submitting. 0DTE options can lose 100% of premium ' +
      'in minutes.',
  };
}
