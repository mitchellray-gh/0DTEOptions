import React, { useMemo } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import NewsFeed from '../components/NewsFeed.jsx';
import { fmt$ } from '../lib/format.js';

const pctSigned = (x) => `${x >= 0 ? '+' : ''}${(x * 100).toFixed(2)}%`;

export default function DiscoverPage() {
  const { watchlist, quotes } = useOutletContext();
  const navigate = useNavigate();

  const movers = useMemo(() => {
    return watchlist
      .map((s) => ({ sym: s, q: quotes[s] }))
      .filter((x) => x.q)
      .sort((a, b) => Math.abs(b.q.change_pct) - Math.abs(a.q.change_pct));
  }, [watchlist, quotes]);

  const gainers = movers.filter((m) => m.q.change_pct > 0).length;
  const losers = movers.filter((m) => m.q.change_pct < 0).length;
  const sentiment = movers.length ? (gainers - losers) / movers.length : 0;

  return (
    <div className="rh-page">
      <h3>Analytics</h3>
      <div className="rh-stats">
        <div className="rh-stat"><div className="k">Gainers</div><div className="v up-fg">{gainers}</div></div>
        <div className="rh-stat"><div className="k">Losers</div><div className="v down-fg">{losers}</div></div>
        <div className="rh-stat"><div className="k">Watchlist bias</div><div className="v" style={{ color: sentiment >= 0 ? 'var(--up)' : 'var(--down)' }}>{sentiment >= 0 ? 'Bullish' : 'Bearish'}</div></div>
        <div className="rh-stat"><div className="k">Tracking</div><div className="v">{watchlist.length}</div></div>
      </div>

      <h3>Today's movers</h3>
      {!movers.length && <div className="rh-empty">Waiting for live quotes…</div>}
      {movers.map(({ sym, q }) => (
        <button key={sym} className="rh-row" onClick={() => navigate(`/instrument/${sym}`)}>
          <div className="rh-col"><span className="rh-sym">{sym}</span></div>
          <div className="rh-quote">
            <div className="rh-price">{fmt$(q.price)}</div>
            <div className={`rh-pct ${q.change_pct >= 0 ? 'up-fg' : 'down-fg'}`}>{pctSigned(q.change_pct)}</div>
          </div>
        </button>
      ))}

      <h3>Headlines</h3>
      <p className="rh-lead">Latest news across the {watchlist.length} tickers you're monitoring.</p>
      <NewsFeed
        tickers={watchlist}
        limit={25}
        showTickers
        emptyText="No recent headlines for your watchlist."
      />
    </div>
  );
}
