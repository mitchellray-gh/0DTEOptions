import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { fetchChains } from './api.js';
import { scanChains } from './lib/scanner.js';
import OpportunityTable from './components/OpportunityTable.jsx';
import RejectionInsights from './components/RejectionInsights.jsx';
import TradeDetail from './components/TradeDetail.jsx';

const LS_WATCHLIST = 'zdte.watchlist';
const LS_SETTINGS = 'zdte.settings';
const DEFAULT_WATCHLIST = ['SPY', 'QQQ', 'IWM'];
const DEFAULT_SETTINGS = { accountSize: 5000, riskPct: 2, minEdge: 5, type: 'all', maxResults: 50 };
const TICKER_RE = /^[A-Z][A-Z.\-]{0,5}$/;

function loadJSON(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) ?? fallback) : fallback;
  } catch {
    return fallback;
  }
}

export default function App() {
  const [watchlist, setWatchlist] = useState(() => {
    const wl = loadJSON(LS_WATCHLIST, DEFAULT_WATCHLIST);
    return Array.isArray(wl) && wl.length ? wl : DEFAULT_WATCHLIST;
  });
  const [settings, setSettings] = useState(() => ({ ...DEFAULT_SETTINGS, ...loadJSON(LS_SETTINGS, {}) }));
  const [tickerInput, setTickerInput] = useState('');
  const [inputError, setInputError] = useState('');

  const [rawChains, setRawChains] = useState(null); // { generated_at, chains, notes }
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => { localStorage.setItem(LS_WATCHLIST, JSON.stringify(watchlist)); }, [watchlist]);
  useEffect(() => { localStorage.setItem(LS_SETTINGS, JSON.stringify(settings)); }, [settings]);

  const filters = useMemo(() => ({
    minEdge: settings.minEdge, type: settings.type,
  }), [settings.minEdge, settings.type]);

  // Pricing + scoring runs entirely in the browser, so changing account size or
  // risk re-scores instantly from the cached chains — no refetch needed.
  const data = useMemo(() => {
    if (!rawChains) return null;
    const scan = scanChains(rawChains.chains, {
      accountSize: settings.accountSize,
      riskPct: settings.riskPct / 100,
      maxResults: settings.maxResults,
    });
    if (rawChains.notes?.length) {
      const fetchNotes = rawChains.notes.filter((n) => /no usable|error/i.test(n));
      scan.notes = [...fetchNotes, ...scan.notes];
    }
    return scan;
  }, [rawChains, settings.accountSize, settings.riskPct, settings.maxResults]);

  // Keep the selected row valid as the scored results change.
  useEffect(() => {
    if (!data?.results?.length) { setSelected(null); return; }
    setSelected((prev) => {
      const keep = prev && data.results.find((r) => r.opportunity.symbol === prev.opportunity.symbol);
      return keep || data.results[0];
    });
  }, [data]);

  const load = useCallback(async (list, nocache = false) => {
    if (!list || !list.length) { setRawChains(null); setError(null); return; }
    setLoading(true);
    setError(null);
    try {
      const json = await fetchChains(list, { nocache });
      setRawChains(json);
      if (!json.chains?.length) {
        setError('No option chains came back — Yahoo may be rate-limiting or these symbols have no 0DTE/near-dated expiry right now.');
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  // Auto-scan the saved watchlist once on mount.
  useEffect(() => { load(watchlist, false); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  const addTicker = () => {
    const t = tickerInput.trim().toUpperCase();
    if (!t) return;
    if (!TICKER_RE.test(t)) { setInputError('Enter a valid symbol, e.g. AAPL'); return; }
    if (watchlist.includes(t)) { setInputError(`${t} is already tracked`); setTickerInput(''); return; }
    if (watchlist.length >= 25) { setInputError('Watchlist is full (25 max)'); return; }
    setWatchlist([...watchlist, t]);
    setTickerInput('');
    setInputError('');
  };

  const removeTicker = (t) => setWatchlist(watchlist.filter((x) => x !== t));

  // Download the current scan as a JSON file the backtester's `replay` mode can
  // settle later (same shape the old /api/opportunities endpoint produced).
  const exportSnapshot = () => {
    if (!data?.results?.length) return;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `snapshot-${new Date().toISOString().replace(/[:.]/g, '-')}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  const generated = useMemo(() => {
    if (!data) return null;
    try { return new Date(data.generated_at).toLocaleTimeString(); }
    catch { return data.generated_at; }
  }, [data]);

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <h1>0DTE Scanner</h1>
          <p className="subtitle">Track tickers and surface undervalued zero-day options.</p>
        </div>
        <div className="status">
          {loading ? <span className="status-scanning">Scanning…</span>
            : data ? <span>Last scan {generated} · <strong>{data.count}</strong> opportunities</span>
            : <span className="muted">No scan yet</span>}
        </div>
      </header>

      <section className="card watchlist">
        <div className="card-head">
          <h2>Watchlist</h2>
          <div className="head-actions">
            <button className="btn ghost" onClick={exportSnapshot}
                    disabled={!data?.results?.length}
                    title="Download the current scan as a replay-compatible JSON snapshot">
              Export snapshot
            </button>
            <button className="btn primary" onClick={() => load(watchlist, true)}
                    disabled={loading || !watchlist.length}>
              {loading ? 'Scanning…' : 'Scan watchlist'}
            </button>
          </div>
        </div>
        <div className="chips">
          {watchlist.length === 0 && <span className="muted">Add a ticker below to start tracking.</span>}
          {watchlist.map((t) => (
            <span className="chip" key={t}>
              {t}
              <button onClick={() => removeTicker(t)} aria-label={`Remove ${t}`} title={`Remove ${t}`}>×</button>
            </span>
          ))}
        </div>
        <div className="add-row">
          <input
            type="text"
            value={tickerInput}
            placeholder="Add ticker (e.g. AAPL)"
            maxLength={6}
            onChange={(e) => { setTickerInput(e.target.value.toUpperCase()); setInputError(''); }}
            onKeyDown={(e) => { if (e.key === 'Enter') addTicker(); }}
          />
          <button className="btn ghost" onClick={addTicker}>Add</button>
        </div>
        {inputError && <div className="input-error">{inputError}</div>}
      </section>

      <section className="toolbar">
        <label className="field">Account ($)
          <input type="number" min="100" step="100" value={settings.accountSize}
                 onChange={(e) => setSettings({ ...settings, accountSize: Number(e.target.value) })} />
        </label>
        <label className="field">Risk / trade (%)
          <input type="number" min="0.1" max="100" step="0.1" value={settings.riskPct}
                 onChange={(e) => setSettings({ ...settings, riskPct: Number(e.target.value) })} />
        </label>
        <label className="field">Min edge (%)
          <input type="number" min="0" step="0.5" value={settings.minEdge}
                 onChange={(e) => setSettings({ ...settings, minEdge: Number(e.target.value) })} />
        </label>
        <label className="field">Type
          <select value={settings.type} onChange={(e) => setSettings({ ...settings, type: e.target.value })}>
            <option value="all">All</option>
            <option value="call">Calls</option>
            <option value="put">Puts</option>
          </select>
        </label>
      </section>

      {error && <div className="banner error">⚠️ {error}</div>}

      {data?.notes?.length ? (
        <details className="notes">
          <summary>Scan notes ({data.notes.length})</summary>
          <ul>{data.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
        </details>
      ) : null}

      <RejectionInsights rejectionSummary={data?.rejection_summary} />

      <div className="content">
        <OpportunityTable
          items={data?.results || []}
          selected={selected}
          onSelect={setSelected}
          filters={filters}
        />
        <TradeDetail item={selected} />
      </div>

      <footer className="disclaimer">
        <strong>Educational use only.</strong> 0DTE options are extremely high-risk and can lose
        100% of premium in minutes. Fair-value estimates use Black-Scholes with a volume-weighted
        reference IV from the same chain — an approximation, not a guarantee. Always verify quotes
        in your broker before trading.
      </footer>
    </div>
  );
}
