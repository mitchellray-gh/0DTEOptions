import React, { useEffect, useMemo, useState } from 'react';
import { fetchOpportunities } from './api.js';
import OpportunityTable from './components/OpportunityTable.jsx';
import TradeDetail from './components/TradeDetail.jsx';

const DEFAULT_TICKERS = 'SPY,QQQ,IWM,DIA';

export default function App() {
  const [tickers, setTickers] = useState(DEFAULT_TICKERS);
  const [accountSize, setAccountSize] = useState(5000);
  const [riskPct, setRiskPct] = useState(2);
  const [maxResults, setMaxResults] = useState(50);

  const [filters, setFilters] = useState({
    minEdge: 5,        // %
    minVolume: 50,
    type: 'all',       // all / call / put
    ticker: '',
  });

  const [data, setData] = useState(null);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = async (nocache = false) => {
    setLoading(true);
    setError(null);
    try {
      const json = await fetchOpportunities({
        tickers,
        account_size: accountSize,
        risk_per_trade_pct: riskPct / 100,
        max_results: maxResults,
        nocache,
      });
      setData(json);
      if (json.results?.length && (!selected ||
          !json.results.find((r) => r.opportunity.symbol === selected.opportunity.symbol))) {
        setSelected(json.results[0]);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(false); /* on mount */ // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const generated = useMemo(() => {
    if (!data) return null;
    try { return new Date(data.generated_at).toLocaleTimeString(); }
    catch { return data.generated_at; }
  }, [data]);

  return (
    <div className="app">
      <header>
        <div>
          <h1>0DTE Options Scanner</h1>
          <div className="subtitle">
            Find undervalued zero-days-to-expiration options and execute the trade with confidence.
          </div>
        </div>
        <div className="status">
          {loading ? 'Scanning…' : data ? `Last scan: ${generated} · ${data.count} opportunities` : ''}
          {error && <div className="status error">Error: {error}</div>}
        </div>
      </header>

      <div className="controls">
        <label>Tickers
          <input type="text" value={tickers} onChange={(e) => setTickers(e.target.value)} placeholder="SPY,QQQ,…" />
        </label>
        <label>Account ($)
          <input type="number" min="100" step="100" value={accountSize}
                 onChange={(e) => setAccountSize(Number(e.target.value))} />
        </label>
        <label>Risk / trade (%)
          <input type="number" min="0.1" max="100" step="0.1" value={riskPct}
                 onChange={(e) => setRiskPct(Number(e.target.value))} />
        </label>
        <label>Max results
          <input type="number" min="1" max="200" value={maxResults}
                 onChange={(e) => setMaxResults(Number(e.target.value))} />
        </label>
        <label>Min edge (%)
          <input type="number" min="0" step="0.5" value={filters.minEdge}
                 onChange={(e) => setFilters({ ...filters, minEdge: Number(e.target.value) })} />
        </label>
        <label>Min volume
          <input type="number" min="0" step="10" value={filters.minVolume}
                 onChange={(e) => setFilters({ ...filters, minVolume: Number(e.target.value) })} />
        </label>
        <label>Type
          <select value={filters.type} onChange={(e) => setFilters({ ...filters, type: e.target.value })}>
            <option value="all">All</option>
            <option value="call">Calls</option>
            <option value="put">Puts</option>
          </select>
        </label>
        <label>Filter ticker
          <input type="text" value={filters.ticker} placeholder="e.g. SPY"
                 onChange={(e) => setFilters({ ...filters, ticker: e.target.value })} />
        </label>
        <button onClick={() => load(false)} disabled={loading}>
          {loading ? 'Loading…' : 'Re-scan'}
        </button>
        <button className="secondary" onClick={() => load(true)} disabled={loading}>
          Force refresh
        </button>
      </div>

      {data?.notes?.length ? (
        <div className="notes">
          <details>
            <summary>Scan notes ({data.notes.length})</summary>
            <ul>{data.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
          </details>
        </div>
      ) : null}

      <div className="content">
        <OpportunityTable
          items={data?.results || []}
          selected={selected}
          onSelect={setSelected}
          filters={filters}
          onFilterChange={setFilters}
        />
        <TradeDetail item={selected} />
      </div>

      <div className="disclaimer">
        ⚠️ <strong>Educational use only.</strong> 0DTE options are extremely high-risk and can lose
        100% of premium in minutes. Fair-value estimates are based on Black-Scholes with a
        volume-weighted reference IV from the same chain — they are an approximation, not a
        guarantee. Always verify quotes in your broker before placing any order, account for
        commissions and slippage, and never trade money you cannot afford to lose.
      </div>
    </div>
  );
}
