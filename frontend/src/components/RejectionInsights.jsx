import React, { useState } from 'react';

const REASON_LABELS = {
  low_bid_ask: { label: 'Low Bid / Ask', icon: '💤', color: '#f87171' },
  low_liquidity: { label: 'Low Liquidity', icon: '🏜️', color: '#fbbf24' },
  no_valid_mid: { label: 'No Valid Mid', icon: '❓', color: '#8b95a7' },
  wide_spread: { label: 'Wide Spread', icon: '↔️', color: '#fb923c' },
  no_edge: { label: 'No Edge (Fairly Priced)', icon: '⚖️', color: '#60a5fa' },
  insufficient_edge: { label: 'Edge Too Small (< 5%)', icon: '📏', color: '#a78bfa' },
};

const REASON_EDUCATION = {
  low_bid_ask: {
    title: 'Why Bid/Ask Matters',
    body: `When you buy an option, you pay the **ask** price. When you sell, you receive the **bid**. 
If the bid is near zero, nobody wants to buy it — meaning you'd be stuck holding a decaying 
asset with no exit. For 0DTE trades, where every minute counts, having a real two-sided market is essential.`,
  },
  low_liquidity: {
    title: 'Volume & Open Interest: Your Liquidity Lifeline',
    body: `**Volume** = contracts traded today. **Open Interest** = total outstanding contracts. 
Together, they tell you how active a strike is. Low liquidity means:
• Wider bid-ask spreads (more cost to you)
• Harder to fill orders at your price
• Risk of being stuck in a position as expiration approaches
We require Volume ≥ 50 and OI ≥ 100 to ensure you can get in AND out.`,
  },
  no_valid_mid: {
    title: 'What is the Midpoint Price?',
    body: `The **mid** = (bid + ask) / 2, which approximates the true market value. 
If we can't compute one, the quotes are stale, missing, or the underlying may be halted. 
Never trade on bad data — this filter protects you from phantom quotes.`,
  },
  wide_spread: {
    title: 'The Spread is Your Hidden Cost',
    body: `The **bid-ask spread** is the "toll" for entering and exiting a position. 
Example: if bid = $0.10 and ask = $0.20, you'd buy at $0.20 but could only sell at $0.10, 
instantly losing 50% — before the underlying even moves. 
We cap the relative spread at 25% of mid to keep this cost manageable.`,
  },
  no_edge: {
    title: 'Fair Value & Edge Explained',
    body: `We compute each contract's **fair value** using the Black-Scholes model and the chain's 
consensus IV (the volume-weighted average of near-the-money implied volatilities). 
If the ask ≥ fair value, the market is pricing the option correctly or even overpricing it. 
There's no statistical advantage to buying it — you'd be paying full price.`,
  },
  insufficient_edge: {
    title: 'Why 5% Minimum Edge?',
    body: `Even a theoretically underpriced option isn't worth trading if the edge is tiny. 
After commissions (~$0.50–$1.30/contract), slippage, and the spread on exit, a 2–3% edge evaporates. 
The 5% threshold ensures meaningful profit potential relative to the **very real** risk of 
losing 100% of your premium on a 0DTE contract that expires worthless.`,
  },
};

function ProgressBar({ value, max, color }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  return (
    <div className="rej-bar-bg">
      <div className="rej-bar-fill" style={{ width: `${pct}%`, background: color }} />
    </div>
  );
}

function SampleRow({ sample }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rej-sample">
      <div className="rej-sample-header" onClick={() => setOpen(!open)}>
        <span className="rej-sample-sym">
          <span className={`badge ${sample.option_type}`}>{sample.option_type.toUpperCase()}</span>
          {' '}{sample.underlying} ${sample.strike}
        </span>
        <span className="rej-sample-toggle">{open ? '▾' : '▸'}</span>
      </div>
      {open && (
        <div className="rej-sample-body">
          <div className="rej-sample-detail">{sample.rejection_detail}</div>
          <div className="rej-sample-data">
            Bid: ${sample.bid.toFixed(2)} · Ask: ${sample.ask.toFixed(2)} · Vol: {sample.volume.toLocaleString()} · OI: {sample.open_interest.toLocaleString()}
          </div>
        </div>
      )}
    </div>
  );
}

function ReasonCard({ reason, count, total, samples }) {
  const [expanded, setExpanded] = useState(false);
  const meta = REASON_LABELS[reason] || { label: reason, icon: '🔍', color: '#8b95a7' };
  const edu = REASON_EDUCATION[reason];

  return (
    <div className="rej-card">
      <div className="rej-card-header" onClick={() => setExpanded(!expanded)}>
        <div className="rej-card-title">
          <span className="rej-icon">{meta.icon}</span>
          <span>{meta.label}</span>
          <span className="rej-count" style={{ color: meta.color }}>{count.toLocaleString()}</span>
        </div>
        <ProgressBar value={count} max={total} color={meta.color} />
        <span className="rej-expand">{expanded ? '▾ Less' : '▸ Learn why'}</span>
      </div>

      {expanded && (
        <div className="rej-card-body">
          {edu && (
            <div className="rej-edu">
              <div className="rej-edu-title">{edu.title}</div>
              <div className="rej-edu-body">{edu.body}</div>
            </div>
          )}
          {samples?.length > 0 && (
            <div className="rej-samples">
              <div className="rej-samples-title">Example contracts filtered out:</div>
              {samples.map((s, i) => <SampleRow key={i} sample={s} />)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function RejectionInsights({ rejectionSummary }) {
  const [collapsed, setCollapsed] = useState(false);

  if (!rejectionSummary || rejectionSummary.total_contracts_scanned === 0) {
    return null;
  }

  const { total_contracts_scanned, total_rejected, total_passed, by_reason, samples } = rejectionSummary;
  const passPct = total_contracts_scanned > 0
    ? ((total_passed / total_contracts_scanned) * 100).toFixed(1)
    : '0.0';

  // Group samples by reason
  const samplesByReason = {};
  for (const s of (samples || [])) {
    if (!samplesByReason[s.rejection_reason]) samplesByReason[s.rejection_reason] = [];
    samplesByReason[s.rejection_reason].push(s);
  }

  // Sort reasons by count descending
  const sortedReasons = Object.entries(by_reason || {}).sort((a, b) => b[1] - a[1]);

  return (
    <div className="rej-widget">
      <div className="rej-widget-header" onClick={() => setCollapsed(!collapsed)}>
        <div>
          <span className="rej-widget-title">🎓 Filter Insights & Options Education</span>
          <span className="rej-widget-subtitle">
            {' '}— {total_contracts_scanned.toLocaleString()} contracts scanned,{' '}
            {total_passed.toLocaleString()} passed ({passPct}%),{' '}
            {total_rejected.toLocaleString()} filtered out
          </span>
        </div>
        <span className="rej-collapse-btn">{collapsed ? '▸ Expand' : '▾ Collapse'}</span>
      </div>

      {!collapsed && (
        <div className="rej-widget-body">
          <div className="rej-overview">
            <div className="rej-overview-bar">
              <div className="rej-overview-pass" style={{ width: `${passPct}%` }}>
                {total_passed > 0 ? `${total_passed} passed` : ''}
              </div>
              <div className="rej-overview-fail" style={{ width: `${100 - parseFloat(passPct)}%` }}>
                {total_rejected > 0 ? `${total_rejected} filtered` : ''}
              </div>
            </div>
            <div className="rej-overview-hint">
              💡 Most option contracts don't meet our quality bar — and that's by design.
              Strict filtering protects your capital. Click each reason below to learn why.
            </div>
          </div>

          <div className="rej-cards">
            {sortedReasons.map(([reason, count]) => (
              <ReasonCard
                key={reason}
                reason={reason}
                count={count}
                total={total_rejected}
                samples={samplesByReason[reason] || []}
              />
            ))}
          </div>

          <div className="rej-glossary">
            <details>
              <summary>📖 Quick Glossary</summary>
              <div className="rej-glossary-grid">
                <div><strong>0DTE</strong></div><div>Zero Days to Expiration — the option expires today</div>
                <div><strong>Bid / Ask</strong></div><div>Bid = highest price a buyer will pay; Ask = lowest price a seller will accept</div>
                <div><strong>Spread</strong></div><div>The gap between bid and ask — your transaction cost</div>
                <div><strong>IV</strong></div><div>Implied Volatility — the market's forecast of how much the stock will move</div>
                <div><strong>Fair Value</strong></div><div>Black-Scholes theoretical price using the chain's consensus IV</div>
                <div><strong>Edge</strong></div><div>How much cheaper the ask is vs fair value (your potential advantage)</div>
                <div><strong>Delta</strong></div><div>How much the option price moves per $1 move in the stock</div>
                <div><strong>Theta</strong></div><div>Time decay — how much value the option loses per day</div>
                <div><strong>Volume</strong></div><div>Number of contracts traded today</div>
                <div><strong>OI</strong></div><div>Open Interest — total outstanding contracts at this strike</div>
              </div>
            </details>
          </div>
        </div>
      )}
    </div>
  );
}
