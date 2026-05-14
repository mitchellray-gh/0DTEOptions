import React from 'react';

const fmtPct = (x) => (x * 100).toFixed(1) + '%';
const fmt$ = (x) => '$' + Number(x).toFixed(2);

export default function OpportunityTable({ items, selected, onSelect, filters, onFilterChange }) {
  const visible = items.filter((it) => {
    const o = it.opportunity;
    if (filters.minEdge && o.edge_pct < filters.minEdge / 100) return false;
    if (filters.minVolume && o.volume < filters.minVolume) return false;
    if (filters.type !== 'all' && o.option_type !== filters.type) return false;
    if (filters.ticker && !o.underlying.toUpperCase().includes(filters.ticker.toUpperCase())) return false;
    return true;
  });

  if (!visible.length) {
    return <div className="empty">No opportunities match the current filters.</div>;
  }

  return (
    <div className="table-wrapper">
      <table>
        <thead>
          <tr>
            <th>Underlying</th>
            <th>Type</th>
            <th>Strike</th>
            <th>Spot</th>
            <th>Bid / Ask</th>
            <th>Fair</th>
            <th>Edge</th>
            <th>Mkt IV</th>
            <th>Ref IV</th>
            <th>Δ</th>
            <th>Vol</th>
            <th>OI</th>
            <th>Min</th>
            <th>Score</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((it) => {
            const o = it.opportunity;
            const isSel = selected && selected.opportunity.symbol === o.symbol;
            return (
              <tr key={o.symbol} className={isSel ? 'selected' : ''} onClick={() => onSelect(it)}>
                <td><strong>{o.underlying}</strong></td>
                <td><span className={`badge ${o.option_type}`}>{o.option_type.toUpperCase()}</span></td>
                <td>{fmt$(o.strike)}</td>
                <td>{fmt$(o.underlying_price)}</td>
                <td>{fmt$(o.bid)} / {fmt$(o.ask)}</td>
                <td>{fmt$(o.fair_value)}</td>
                <td className="edge-pos">{fmtPct(o.edge_pct)}</td>
                <td>{o.market_iv != null ? fmtPct(o.market_iv) : '—'}</td>
                <td>{fmtPct(o.reference_iv)}</td>
                <td>{o.delta.toFixed(2)}</td>
                <td>{o.volume.toLocaleString()}</td>
                <td>{o.open_interest.toLocaleString()}</td>
                <td>{o.minutes_to_expiry}</td>
                <td>{o.score.toFixed(1)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
