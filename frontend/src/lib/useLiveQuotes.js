// Auto-refreshing quote hook. Polls /api/quote on an interval, pauses when the
// browser tab is hidden (Robinhood-style: no wasted requests in the background),
// and exposes the latest snapshot plus a freshness flag for the "live" dot.
import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchQuotes } from '../api.js';

/**
 * @param {string[]} tickers  symbols to poll
 * @param {Object} opts       { intervalMs = 10000, enabled = true }
 * @returns { quotes, updatedAt, loading, error, fresh, refresh }
 */
export function useLiveQuotes(tickers, { intervalMs = 10_000, enabled = true } = {}) {
  const [quotes, setQuotes] = useState({});
  const [updatedAt, setUpdatedAt] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [fresh, setFresh] = useState(false);
  const timer = useRef(null);
  const key = (tickers || []).join(',');

  const poll = useCallback(async () => {
    if (!key) { setQuotes({}); return; }
    setLoading(true);
    try {
      const list = key.split(',');
      const json = await fetchQuotes(list);
      setQuotes((prev) => ({ ...prev, ...(json.quotes || {}) }));
      setUpdatedAt(new Date());
      setFresh(true);
      setError(null);
    } catch (e) {
      setError(e.message);
      setFresh(false);
    } finally {
      setLoading(false);
    }
  }, [key]);

  useEffect(() => {
    if (!enabled || !key) return undefined;
    let cancelled = false;
    const tick = () => { if (!cancelled) poll(); };
    tick(); // immediate
    const start = () => {
      if (timer.current) clearInterval(timer.current);
      timer.current = setInterval(() => {
        if (document.visibilityState === 'visible') poll();
      }, intervalMs);
    };
    start();
    const onVis = () => { if (document.visibilityState === 'visible') poll(); };
    document.addEventListener('visibilitychange', onVis);
    return () => {
      cancelled = true;
      if (timer.current) clearInterval(timer.current);
      document.removeEventListener('visibilitychange', onVis);
    };
  }, [enabled, key, intervalMs, poll]);

  // Mark quotes stale if we haven't refreshed in a while.
  useEffect(() => {
    if (!updatedAt) return undefined;
    const t = setTimeout(() => setFresh(false), intervalMs * 2.5);
    return () => clearTimeout(t);
  }, [updatedAt, intervalMs]);

  return { quotes, updatedAt, loading, error, fresh, refresh: poll };
}
