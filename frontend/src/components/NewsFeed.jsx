// Reusable Robinhood-style news feed. Fetches recent headlines for a list of
// tickers from /api/news and renders them with thumbnails, source, and age.
import React, { useEffect, useState } from 'react';
import { fetchNews } from '../api.js';

export function timeAgo(iso) {
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

/**
 * @param {string[]} tickers   symbols to pull headlines for
 * @param {number}   limit     max headlines
 * @param {boolean}  showTickers  render per-story ticker tags (useful for a
 *                                multi-symbol feed; off for a single instrument)
 * @param {string}   emptyText    message when there are no headlines
 */
export default function NewsFeed({ tickers, limit = 20, showTickers = true, emptyText }) {
  const [items, setItems] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const key = (tickers || []).join(',');

  useEffect(() => {
    if (!key) { setItems([]); return undefined; }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchNews(key.split(','), { limit })
      .then((d) => { if (!cancelled) setItems(d.items || []); })
      .catch((e) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [key, limit]);

  if (loading && !items) return <div className="rh-empty">Loading headlines…</div>;
  if (error) return <div className="banner error">⚠️ {error}</div>;
  if (items && !items.length) {
    return <div className="rh-empty">{emptyText || 'No recent headlines.'}</div>;
  }

  return (
    <>
      {(items || []).map((item) => (
        <a
          key={item.uuid}
          className="rh-news"
          href={item.link || '#'}
          target="_blank"
          rel="noreferrer noopener"
        >
          <div className="rh-news-body">
            <div className="rh-news-src">{item.publisher}</div>
            <div className="rh-news-title">{item.title}</div>
            <div className="rh-news-meta">
              {showTickers && (item.tickers || []).map((t) => (
                <span key={t} className="rh-news-ticker">{t}</span>
              ))}
              {timeAgo(item.published_at)}
            </div>
          </div>
          {item.thumbnail && <img src={item.thumbnail} alt="" loading="lazy" />}
        </a>
      ))}
    </>
  );
}
