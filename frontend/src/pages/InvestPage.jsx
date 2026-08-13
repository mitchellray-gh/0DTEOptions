import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import Sparkline from '../components/Sparkline.jsx';
import { fetchHistory } from '../api.js';
import { fmt$ } from '../lib/format.js';

const fmtPct = (x) => `${x >= 0 ? '+' : ''}${(x * 100).toFixed(2)}%`;

export default function InvestPage() {
  const { watchlist, addTicker, removeTicker, quotes } = useOutletContext();
  const navigate = useNavigate();
  const [input, setInput] = useState('');
  const [err, setErr] = useState('');
  const [sparks, setSparks] = useState({}); // sym -> [closes]

  // Fetch intraday closes once per symbol for the row sparklines.
  useEffect(() => {
    let cancelled = false;
    watchlist.forEach((sym) => {
      if (sparks[sym]) return;
      fetchHistory(sym, '1d')
        .then((d) => {
          if (cancelled) return;
          const closes = (d.bars || []).map((b) => Number(b.c)).filter(Number.isFinite);
          setSparks((prev) => ({ ...prev, [sym]: closes }));
        })
        .catch(() => { /* ignore per-symbol failures */ });
    });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watchlist]);

  const onAdd = () => {
    const e = addTicker(input);
    if (e) { setErr(e); return; }
    setInput('');
    setErr('');
  };

  const totalUp = useMemo(() => {
    const vals = watchlist.map((s) => quotes[s]?.change_pct).filter(Number.isFinite);
    if (!vals.length) return null;
    return vals.reduce((a, b) => a + b, 0) / vals.length;
  }, [watchlist, quotes]);

  return (
    <div className="rh-page">
      <div className="rh-card">
        <div className="rh-label">Watchlist snapshot</div>
        <div className="rh-hero-value">{watchlist.length} symbols</div>
        {totalUp != null && (
          <div className={`rh-change ${totalUp >= 0 ? 'up' : 'down'}`}>
            <span className="arrow">{totalUp >= 0 ? '▲' : '▼'}</span>
            avg {fmtPct(totalUp)} today
          </div>
        )}
      </div>

      <h3>Watchlist</h3>
      {watchlist.length === 0 && <div className="rh-empty">Add a ticker to start tracking.</div>}
      {watchlist.map((sym) => {
        const q = quotes[sym];
        const up = q ? q.change >= 0 : true;
        return (
          <button key={sym} className="rh-row" onClick={() => navigate(`/instrument/${sym}`)}>
            <div className="rh-col">
              <span className="rh-sym">{sym}</span>
              <span className="rh-name">0DTE</span>
            </div>
            <div className="rh-spark">
              <Sparkline points={sparks[sym]} up={q ? up : undefined} width={90} />
            </div>
            <div className="rh-quote">
              <div className="rh-price">{q ? fmt$(q.price) : '—'}</div>
              <div className={`rh-pct ${up ? 'up-fg' : 'down-fg'}`}>
                {q ? fmtPct(q.change_pct) : ''}
              </div>
            </div>
            <span
              role="button"
              tabIndex={-1}
              className="rh-pill"
              onClick={(e) => { e.stopPropagation(); removeTicker(sym); }}
              title={`Remove ${sym}`}
              style={{ marginLeft: 8 }}
            >
              ✕
            </span>
          </button>
        );
      })}

      <h3>Add symbol</h3>
      <div className="rh-inline">
        <input
          className="rh-input"
          style={{ maxWidth: 200 }}
          value={input}
          placeholder="e.g. AAPL"
          maxLength={6}
          onChange={(e) => { setInput(e.target.value.toUpperCase()); setErr(''); }}
          onKeyDown={(e) => { if (e.key === 'Enter') onAdd(); }}
        />
        <button className="rh-btn sm" onClick={onAdd}>Add</button>
      </div>
      {err && <div className="input-error">{err}</div>}

      <p className="rh-lead" style={{ marginTop: 20 }}>
        Tap a symbol to see its live chart and ranked 0DTE opportunities with coaching.
        Educational use only — quotes are delayed and no real orders are placed.
      </p>
    </div>
  );
}
