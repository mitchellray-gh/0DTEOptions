import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import { fetchNews } from '../api.js';
import { fmt$ } from '../lib/format.js';

const pctSigned = (x) => `${x >= 0 ? '+' : ''}${(x * 100).toFixed(2)}%`;

function timeAgo(iso) {
  if (!iso) return '';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

export default function DiscoverPage() {
  const { watchlist, quotes } = useOutletContext();
  const navigate = useNavigate();
  const [news, setNews] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchNews(watchlist, { limit: 25 })
      .then((d) => { if (!cancelled) setNews(d.items || []); })
      .catch((e) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watchlist.join(',')]);

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
        <div className="rh-stat"><div className="k">Headlines</div><div className="v">{news?.length ?? '—'}</div></div>
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

      <h3>News</h3>
      {loading && <div className="rh-empty">Loading headlines…</div>}
      {error && <div className="banner error">⚠️ {error}</div>}
      {news && !news.length && !loading && <div className="rh-empty">No recent headlines for your watchlist.</div>}
      {(news || []).map((item) => (
        <a key={item.uuid} className="rh-news" href={item.link || '#'} target="_blank" rel="noreferrer noopener">
          <div className="rh-news-body">
            <div className="rh-news-src">{item.publisher}</div>
            <div className="rh-news-title">{item.title}</div>
            <div className="rh-news-meta">
              {(item.tickers || []).map((t) => <span key={t} className="rh-news-ticker">{t}</span>)}
              {timeAgo(item.published_at)}
            </div>
          </div>
          {item.thumbnail && <img src={item.thumbnail} alt="" loading="lazy" />}
        </a>
      ))}
    </div>
  );
}
