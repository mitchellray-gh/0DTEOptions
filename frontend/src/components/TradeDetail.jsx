import React from 'react';

const fmt$ = (x) => '$' + Number(x).toFixed(2);
const fmtPct = (x) => (x * 100).toFixed(1) + '%';

export default function TradeDetail({ item }) {
  if (!item) {
    return (
      <aside className="detail">
        <h2>Select an opportunity</h2>
        <p style={{ color: 'var(--muted)', fontSize: 13 }}>
          Click any row in the table to see the exact trade plan: contract,
          limit price, position size, breakeven, take-profit, and stop-loss.
        </p>
      </aside>
    );
  }
  const o = item.opportunity;
  const p = item.plan;
  return (
    <aside className="detail">
      <h2>{p.side_human}</h2>
      <div className="sym">{p.contract_symbol}</div>

      <div className="action">{p.action.replace('_', ' ')} @ {fmt$(p.limit_price)}</div>

      <h3>Trade plan</h3>
      <div className="row"><span className="k">Contracts</span><span className="v">{p.suggested_contracts}</span></div>
      <div className="row"><span className="k">Cost / contract</span><span className="v">{fmt$(p.cost_per_contract_usd)}</span></div>
      <div className="row"><span className="k">Total cost</span><span className="v">{fmt$(p.total_cost_usd)}</span></div>
      <div className="row"><span className="k">Max loss</span><span className="v">{fmt$(p.max_loss_usd)}</span></div>
      <div className="row"><span className="k">Breakeven (underlying)</span><span className="v">{fmt$(p.breakeven_underlying_price)}</span></div>
      <div className="row"><span className="k">Take-profit limit</span><span className="v">{fmt$(p.target_exit_price)}</span></div>
      <div className="row"><span className="k">Target profit</span><span className="v">{fmt$(p.target_profit_usd)}</span></div>
      <div className="row"><span className="k">Stop-loss</span><span className="v">{fmt$(p.stop_loss_price)} ({fmt$(p.stop_loss_usd)})</span></div>

      <h3>Why it's mispriced</h3>
      <div className="rationale">{p.rationale}</div>

      <h3>Step-by-step</h3>
      <ol>
        {p.steps.map((s, i) => <li key={i}>{s.replace(/^\d+\.\s*/, '')}</li>)}
      </ol>

      <h3>Contract snapshot</h3>
      <div className="row"><span className="k">Underlying</span><span className="v">{o.underlying} @ {fmt$(o.underlying_price)}</span></div>
      <div className="row"><span className="k">Expiration</span><span className="v">{o.expiration} ({o.minutes_to_expiry} min)</span></div>
      <div className="row"><span className="k">Bid / Ask</span><span className="v">{fmt$(o.bid)} / {fmt$(o.ask)}</span></div>
      <div className="row"><span className="k">Mid</span><span className="v">{fmt$(o.mid)}</span></div>
      <div className="row"><span className="k">Fair value</span><span className="v">{fmt$(o.fair_value)}</span></div>
      <div className="row"><span className="k">Edge</span><span className="v edge-pos">{fmtPct(o.edge_pct)} ({fmt$(o.edge_abs)}/sh)</span></div>
      <div className="row"><span className="k">Market IV</span><span className="v">{o.market_iv != null ? fmtPct(o.market_iv) : '—'}</span></div>
      <div className="row"><span className="k">Reference IV</span><span className="v">{fmtPct(o.reference_iv)}</span></div>

      <h3>Greeks</h3>
      <div className="row"><span className="k">Delta</span><span className="v">{o.delta.toFixed(3)}</span></div>
      <div className="row"><span className="k">Gamma</span><span className="v">{o.gamma.toFixed(4)}</span></div>
      <div className="row"><span className="k">Theta / day</span><span className="v">{fmt$(o.theta_per_day)}</span></div>
      <div className="row"><span className="k">Vega / vol-pt</span><span className="v">{fmt$(o.vega_per_volpt)}</span></div>
    </aside>
  );
}
