import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import NewsFeed from '../components/NewsFeed.jsx';
import { fetchMarketMovers } from '../api.js';
import { fmt$ } from '../lib/format.js';

const pctSigned = (x) => `${x >= 0 ? '+' : ''}${(x * 100).toFixed(2)}%`;

export default function DiscoverPage() {
  const { watchlist, quotes } = useOutletContext();
  const navigate = useNavigate();
  const [moversData, setMoversData] = useState(null);
  const [moverTab, setMoverTab] = useState('gainers');

  useEffect(() => {
    let cancelled = false;
    fetchMarketMovers().then((d) => { if (!cancelled) setMoversData(d); }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  // watchlist live-quote stats for analytics summary
  const watchlistStats = useMemo(() => {
    const wl = watchlist.map((s) => ({ sym: s, q: quotes[s] })).filter((x) => x.q);
    const gainers = wl.filter((m) => m.q.change_pct > 0).length;
    const losers = wl.filter((m) => m.q.change_pct < 0).length;
    return { gainers, losers, sentiment: wl.length ? (gainers - losers) / wl.length : 0 };
  }, [watchlist, quotes]);

  const avMovers = moversData ? {
    gainers: (moversData.top_gainers || []).slice(0, 8),
    losers: (moversData.top_losers || []).slice(0, 8),
    active: (moversData.most_actively_traded || []).slice(0, 8),
  } : null;

  return (
    <div className="rh-page">
      <h3>Analytics</h3>
      <div className="rh-stats">
        <div className="rh-stat"><div className="k">Gainers</div><div className="v up-fg">{gainers}</div></div>
        <div className="rh-stat"><div className="k">Losers</div><div className="v down-fg">{watchlistStats.losers}</div></div>
        <div className="rh-stat"><div className="k">Watchlist bias</div><div className="v" style={{ color: watchlistStats.sentiment >= 0 ? 'var(--up)' : 'var(--down)' }}>{watchlistStats.sentiment >= 0 ? 'Bullish' : 'Bearish'}</div></div>
        <div className="rh-stat"><div className="k">Tracking</div><div className="v">{watchlist.length}</div></div>
      </div>

      <h3>US Market movers <span className="rh-name" style={{ fontWeight: 400 }}>(Alpha Vantage)</span></h3>
      <div className="rh-seg" style={{ marginBottom: 10 }}>
        <button className={moverTab === 'gainers' ? 'active-buy' : ''} onClick={() => setMoverTab('gainers')}>Top Gainers</button>
        <button className={moverTab === 'losers' ? 'active-sell' : ''} onClick={() => setMoverTab('losers')}>Top Losers</button>
        <button className={moverTab === 'active' ? 'active-buy' : ''} onClick={() => setMoverTab('active')}>Most Active</button>
      </div>
      {!avMovers && <div className="rh-empty">Loading market data…</div>}
      {avMovers && (moverTab === 'gainers' ? avMovers.gainers : moverTab === 'losers' ? avMovers.losers : avMovers.active).map((m) => {
        const up = !m.change_amount?.startsWith('-');
        return (
          <button key={m.ticker} className="rh-row" onClick={() => navigate(`/instrument/${m.ticker}`)}>
            <div className="rh-col"><span className="rh-sym">{m.ticker}</span></div>
            <div className="rh-quote">
              <div className="rh-price">{m.price ? fmt$(Number(m.price)) : '—'}</div>
              <div className={`rh-pct ${up ? 'up-fg' : 'down-fg'}`}>{m.change_percentage}</div>
            </div>
          </button>
        );
      })}

      <h3>Headlines</h3>
      <p className="rh-lead">Latest news with AI sentiment across the {watchlist.length} tickers you're monitoring.</p>
      <NewsFeed
        tickers={watchlist}
        limit={25}
        showTickers
        emptyText="No recent headlines for your watchlist."
      />
    </div>
  );
}
