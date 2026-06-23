import React, { useState } from 'react';
import { fmt$, fmtPct } from '../lib/format.js';

const URGENCY_LABEL = { high: '🔴 Act Now', medium: '🟡 Watch Closely', low: '🟢 Time Available' };
const CONFIDENCE_LABEL = { strong: '💪 Strong', moderate: '👍 Moderate', speculative: '🤔 Speculative' };

function CoachingPanel({ coaching, plan }) {
  if (!coaching) return null;
  return (
    <div className="coaching-panel">
      <div className="coaching-badges">
        <span className={`coaching-badge urgency-${coaching.urgency}`}>{URGENCY_LABEL[coaching.urgency] || coaching.urgency}</span>
        <span className={`coaching-badge confidence-${coaching.confidence}`}>{CONFIDENCE_LABEL[coaching.confidence] || coaching.confidence}</span>
      </div>

      <div className="coaching-section">
        <div className="coaching-label">🎯 What to Do</div>
        <div className="coaching-action-box">{coaching.action_summary}</div>
      </div>

      <div className="coaching-section">
        <div className="coaching-label">💡 Why This Trade?</div>
        <div className="coaching-text">{coaching.why}</div>
      </div>

      <div className="coaching-section">
        <div className="coaching-label">📋 How to Enter</div>
        <div className="coaching-text">{coaching.entry_instruction}</div>
      </div>

      <div className="coaching-columns">
        <div className="coaching-section coaching-col">
          <div className="coaching-label">💰 Profit Target</div>
          <div className="coaching-text coaching-good">{coaching.expected_profit}</div>
        </div>
        <div className="coaching-section coaching-col">
          <div className="coaching-label">⚠️ Max Risk</div>
          <div className="coaching-text coaching-warn">{coaching.max_risk}</div>
        </div>
      </div>

      <div className="coaching-section">
        <div className="coaching-label">🚪 Exit Plan</div>
        <div className="coaching-text">{coaching.exit_plan}</div>
      </div>

      <div className="coaching-section">
        <div className="coaching-label">👀 Watch List</div>
        <ul className="coaching-watch">
          {coaching.watch_list.map((item, i) => <li key={i}>{item}</li>)}
        </ul>
      </div>
    </div>
  );
}

export default function OpportunityTable({ items, selected, onSelect, filters }) {
  const [expandedSymbol, setExpandedSymbol] = useState(null);

  const visible = items.filter((it) => {
    const o = it.opportunity;
    if (filters.minEdge && o.edge_pct < filters.minEdge / 100) return false;
    if (filters.type !== 'all' && o.option_type !== filters.type) return false;
    return true;
  });

  if (!visible.length) {
    return <div className="empty">No opportunities match the current filters.</div>;
  }

  const handleRowClick = (it) => {
    onSelect(it);
    setExpandedSymbol((prev) => prev === it.opportunity.symbol ? null : it.opportunity.symbol);
  };

  return (
    <div className="table-wrapper">
      <table>
        <thead>
          <tr>
            <th>Action</th>
            <th>Underlying</th>
            <th>Type</th>
            <th>Strike</th>
            <th>Spot</th>
            <th>Bid / Ask</th>
            <th>Fair</th>
            <th>Edge</th>
            <th>Δ</th>
            <th>Vol</th>
            <th>Score</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {visible.map((it) => {
            const o = it.opportunity;
            const c = it.coaching;
            const isSel = selected && selected.opportunity.symbol === o.symbol;
            const isExpanded = expandedSymbol === o.symbol;
            return (
              <React.Fragment key={o.symbol}>
                <tr className={`${isSel ? 'selected' : ''} ${isExpanded ? 'expanded-parent' : ''}`} onClick={() => handleRowClick(it)}>
                  <td>
                    <span className="action-pill">{c ? c.action_summary : `Buy ${o.option_type.toUpperCase()}`}</span>
                  </td>
                  <td><strong>{o.underlying}</strong></td>
                  <td><span className={`badge ${o.option_type}`}>{o.option_type.toUpperCase()}</span></td>
                  <td>{fmt$(o.strike)}</td>
                  <td>{fmt$(o.underlying_price)}</td>
                  <td>{fmt$(o.bid)} / {fmt$(o.ask)}</td>
                  <td>{fmt$(o.fair_value)}</td>
                  <td className="edge-pos">{fmtPct(o.edge_pct)}</td>
                  <td>{o.delta.toFixed(2)}</td>
                  <td>{o.volume.toLocaleString()}</td>
                  <td>{o.score.toFixed(1)}</td>
                  <td className="expand-arrow">{isExpanded ? '▲' : '▼'}</td>
                </tr>
                {isExpanded && (
                  <tr className="coaching-row">
                    <td colSpan="12">
                      <CoachingPanel coaching={c} plan={it.plan} />
                    </td>
                  </tr>
                )}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
