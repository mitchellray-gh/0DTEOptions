import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate, useOutletContext, useParams } from 'react-router-dom';
import PriceChart from '../components/PriceChart.jsx';
import { fetchChains, fetchHistory } from '../api.js';
import { scanChains } from '../lib/scanner.js';
import { buyToOpen, loadPaper } from '../lib/paper.js';
import { fmt$, fmtPct } from '../lib/format.js';

const RANGES = ['1d', '5d', '1mo', '3mo', '6mo', '1y'];
const pctSigned = (x) => `${x >= 0 ? '+' : ''}${(x * 100).toFixed(2)}%`;

export default function InstrumentPage() {
  const { symbol } = useParams();
  const sym = (symbol || '').toUpperCase();
  const navigate = useNavigate();
  const { quotes, settings } = useOutletContext();

  const [range, setRange] = useState('1d');
  const [hist, setHist] = useState(null);
  const [chains, setChains] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [qty, setQty] = useState(1);
  const [toast, setToast] = useState(null);

  const q = quotes[sym];

  useEffect(() => {
    let cancelled = false;
    fetchHistory(sym, range).then((d) => { if (!cancelled) setHist(d); }).catch(() => {});
    return () => { cancelled = true; };
  }, [sym, range]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchChains([sym], { nocache: false })
      .then((json) => { if (!cancelled) setChains(json); })
      .catch((e) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [sym]);

  const scan = useMemo(() => {
    if (!chains?.chains?.length) return null;
    return scanChains(chains.chains, {
      accountSize: settings.accountSize,
      riskPct: settings.riskPct / 100,
      maxResults: 25,
    });
  }, [chains, settings.accountSize, settings.riskPct]);

  const results = useMemo(() => {
    let items = scan?.results || [];
    if (settings.type !== 'all') items = items.filter((r) => r.opportunity.option_type === settings.type);
    if (settings.minEdge) items = items.filter((r) => r.opportunity.edge_pct * 100 >= settings.minEdge);
    return items;
  }, [scan, settings.type, settings.minEdge]);

  const selected = useMemo(
    () => results.find((r) => r.opportunity.symbol === selectedId) || results[0] || null,
    [results, selectedId]
  );

  const prevClose = q?.prev_close ?? null;

  const doBuy = () => {
    if (!selected) return;
    const o = selected.opportunity;
    const res = buyToOpen(loadPaper(), o, qty, { price: o.ask });
    if (!res.ok) { setToast({ err: res.error }); return; }
    setToast({ ok: `Bought ${qty} ${sym} ${o.strike} ${o.option_type.toUpperCase()} @ ${fmt$(o.ask)} (paper).` });
  };

  return (
    <div className="rh-page">
      <button className="rh-btn secondary sm" onClick={() => navigate(-1)}>← Back</button>

      <div style={{ marginTop: 12 }}>
        <div className="rh-label">{sym}</div>
        <div className="rh-hero-value">{q ? fmt$(q.price) : '—'}</div>
        {q && (
          <div className={`rh-change ${q.change >= 0 ? 'up' : 'down'}`}>
            <span className="arrow">{q.change >= 0 ? '▲' : '▼'}</span>
            {fmt$(Math.abs(q.change))} ({pctSigned(q.change_pct)}) today
          </div>
        )}
      </div>

      <PriceChart bars={hist?.bars} prevClose={range === '1d' ? prevClose : null} />
      <div className="rh-range-row">
        {RANGES.map((r) => (
          <button
            key={r}
            className={`rh-range-btn${r === range ? ' active' : ''}`}
            onClick={() => setRange(r)}
          >
            {r.toUpperCase()}
          </button>
        ))}
      </div>

      <h3>0DTE opportunities</h3>
      {loading && <div className="rh-empty">Scanning the chain…</div>}
      {error && <div className="banner error">⚠️ {error}</div>}
      {!loading && !error && !results.length && (
        <div className="rh-empty">
          No qualifying 0DTE contracts right now. Yahoo may be rate-limiting, the
          market may be closed, or nothing beats the edge/liquidity filters.
        </div>
      )}

      {results.map((r) => {
        const o = r.opportunity;
        const active = selected && o.symbol === selected.opportunity.symbol;
        return (
          <button
            key={o.symbol}
            className="rh-row"
            style={active ? { borderBottom: '1px solid var(--accent)' } : undefined}
            onClick={() => setSelectedId(o.symbol)}
          >
            <div className="rh-col">
              <span className="rh-sym">
                ${o.strike} <span className={`badge ${o.option_type}`}>{o.option_type.toUpperCase()}</span>
              </span>
              <span className="rh-name">{o.minutes_to_expiry}m left · IV {fmtPct(o.reference_iv)}</span>
            </div>
            <div className="rh-quote">
              <div className="rh-price">{fmt$(o.ask)}</div>
              <div className="rh-pct up-fg">edge {fmtPct(o.edge_pct)}</div>
            </div>
          </button>
        );
      })}

      {selected && <CoachingCard result={selected} />}

      {selected && (
        <div className="rh-card rh-ticket" style={{ marginTop: 14 }}>
          <div className="rh-label">Paper trade</div>
          <div className="rh-inline" style={{ marginTop: 8 }}>
            <input
              className="rh-input"
              style={{ maxWidth: 90 }}
              type="number"
              min="1"
              value={qty}
              onChange={(e) => setQty(Math.max(1, Math.trunc(Number(e.target.value) || 1)))}
            />
            <button className="rh-btn" style={{ flex: 1 }} onClick={doBuy}>
              Buy {qty} @ {fmt$(selected.opportunity.ask)}
            </button>
          </div>
          <p className="rh-lead" style={{ marginTop: 8 }}>
            Virtual order — routed to your paper portfolio, not a broker. Manage it on the Practice tab.
          </p>
          {toast?.ok && <div className="rh-pill done" style={{ marginTop: 6 }}>{toast.ok}</div>}
          {toast?.err && <div className="input-error">{toast.err}</div>}
        </div>
      )}
    </div>
  );
}

function CoachingCard({ result }) {
  const { opportunity: o, plan, coaching: c } = result;
  return (
    <div className="rh-coach">
      <h4>Coaching · {c.confidence} confidence · {c.urgency} urgency</h4>
      <div className="rh-coach-line"><span className="ico">🎯</span><span><strong>What:</strong> {c.action_summary}</span></div>
      <div className="rh-coach-line"><span className="ico">💡</span><span><strong>Why:</strong> {c.why}</span></div>
      <div className="rh-coach-line"><span className="ico">📐</span><span><strong>Greeks:</strong> delta {o.delta.toFixed(2)} (moves ${Math.abs(o.delta).toFixed(2)} per $1), theta {fmt$(o.theta_per_day)}/day decay.</span></div>
      <div className="rh-coach-line"><span className="ico">🟢</span><span><strong>Profit target:</strong> {c.expected_profit}</span></div>
      <div className="rh-coach-line"><span className="ico">🛑</span><span><strong>Max risk:</strong> {c.max_risk}</span></div>
      <div className="rh-coach-line"><span className="ico">🚪</span><span><strong>Exit plan:</strong> {c.exit_plan}</span></div>
      <div className="rh-coach-line"><span className="ico">📋</span><span><strong>Breakeven:</strong> {fmt$(plan.breakeven_underlying_price)} · Limit {fmt$(plan.limit_price)} · {plan.suggested_contracts} contract(s)</span></div>
    </div>
  );
}
