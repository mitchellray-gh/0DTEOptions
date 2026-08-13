import React, { useEffect, useMemo, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { fetchSpreads } from '../api.js';
import { fmt$ } from '../lib/format.js';

const pct = (x) => `${(x * 100).toFixed(0)}%`;

export default function SpreadsPage() {
  const { watchlist, settings } = useOutletContext();
  const [minPop, setMinPop] = useState(0.85);
  const [maxWidth, setMaxWidth] = useState(5);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);

  const load = () => {
    if (!watchlist.length) return;
    setLoading(true);
    setError(null);
    fetchSpreads(watchlist, {
      accountSize: settings.accountSize,
      riskPct: settings.riskPct / 100,
      minPop,
      maxWidth,
    })
      .then((d) => setData(d))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  const spreads = data?.spreads || [];
  const sel = useMemo(
    () => spreads.find((s) => s.short_symbol === selected) || spreads[0] || null,
    [spreads, selected]
  );

  return (
    <div className="rh-page">
      <div className="rh-card">
        <div className="rh-label">Defined-risk credit spreads</div>
        <p className="rh-lead" style={{ marginTop: 4 }}>
          The high-win-rate strategy: <strong>sell</strong> a vertical spread whose short
          strike likely expires out-of-the-money. Max loss is capped (width − credit).
          Backtested to ~82% win rate at POP ≥ 85%.
        </p>
        <div className="rh-inline" style={{ marginTop: 10 }}>
          <div style={{ flex: 1 }}>
            <span className="rh-label">Min win prob</span>
            <select className="rh-input" value={minPop} onChange={(e) => setMinPop(Number(e.target.value))}>
              <option value={0.80}>80%</option>
              <option value={0.85}>85%</option>
              <option value={0.90}>90%</option>
            </select>
          </div>
          <div style={{ flex: 1 }}>
            <span className="rh-label">Max width ($)</span>
            <select className="rh-input" value={maxWidth} onChange={(e) => setMaxWidth(Number(e.target.value))}>
              <option value={2}>2</option>
              <option value={5}>5</option>
              <option value={10}>10</option>
            </select>
          </div>
        </div>
        <button className="rh-btn block" style={{ marginTop: 12 }} onClick={load} disabled={loading}>
          {loading ? 'Scanning…' : 'Scan watchlist for spreads'}
        </button>
      </div>

      {error && <div className="banner error">⚠️ {error}</div>}
      {!loading && data && !spreads.length && (
        <div className="rh-empty">
          No spreads met the {pct(minPop)} win-probability gate right now. Try a lower
          probability or wider width, or scan when the market is open.
        </div>
      )}

      {spreads.map((s) => {
        const active = sel && s.short_symbol === sel.short_symbol;
        const bull = s.spread_type === 'put_credit';
        return (
          <button
            key={s.short_symbol + s.long_symbol}
            className="rh-row"
            style={active ? { borderBottom: '1px solid var(--accent)' } : undefined}
            onClick={() => setSelected(s.short_symbol)}
          >
            <div className="rh-col">
              <span className="rh-sym">
                ${s.short_strike}/${s.long_strike}{' '}
                <span className={`badge ${bull ? 'call' : 'put'}`}>
                  {bull ? 'PUT CREDIT' : 'CALL CREDIT'}
                </span>
              </span>
              <span className="rh-name">{s.underlying} · {s.minutes_to_expiry}m · R:R {s.reward_risk.toFixed(2)}</span>
            </div>
            <div className="rh-quote">
              <div className="rh-price up-fg">{pct(s.pop)} win</div>
              <div className="rh-pct">+{fmt$(s.max_profit_usd)}</div>
            </div>
          </button>
        );
      })}

      {sel && (
        <div className="rh-coach" style={{ marginTop: 12 }}>
          <h4>
            {sel.spread_type === 'put_credit' ? 'Put' : 'Call'} credit spread ·{' '}
            {pct(sel.pop)} modeled win
          </h4>
          <div className="rh-coach-line"><span className="ico">🎯</span><span><strong>Trade:</strong> Sell the ${sel.short_strike} {sel.spread_type === 'put_credit' ? 'put' : 'call'}, buy the ${sel.long_strike} {sel.spread_type === 'put_credit' ? 'put' : 'call'} ({sel.contracts}× on {sel.underlying}) for a ${sel.credit.toFixed(2)} credit.</span></div>
          <div className="rh-coach-line"><span className="ico">🟢</span><span><strong>Max profit:</strong> {fmt$(sel.max_profit_usd)} — kept if {sel.underlying} stays {sel.spread_type === 'put_credit' ? 'above' : 'below'} ${sel.short_strike} at the close.</span></div>
          <div className="rh-coach-line"><span className="ico">🛑</span><span><strong>Max loss:</strong> {fmt$(sel.max_loss_usd)} — capped by the ${sel.long_strike} long leg (defined risk).</span></div>
          <div className="rh-coach-line"><span className="ico">⚖️</span><span><strong>Breakeven:</strong> ${sel.breakeven.toFixed(2)} · <strong>Win prob:</strong> {pct(sel.pop)} · <strong>Width:</strong> ${sel.width}</span></div>
          <div className="rh-coach-line"><span className="ico">📋</span><span><strong>Manage:</strong> Take profit at ~50% of the credit; stop if the loss hits ~2× the credit. Don't hold a losing spread into the last minutes.</span></div>
        </div>
      )}

      <footer className="disclaimer" style={{ marginTop: 16 }}>
        <strong>Educational only.</strong> {data?.disclaimer || 'Defined-risk credit spreads cap max loss at width − credit. Modeled win probability, not a guarantee.'}
      </footer>
    </div>
  );
}
