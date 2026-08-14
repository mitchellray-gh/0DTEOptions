// Thin API helper. The Python backend is now only a data proxy: it returns the
// raw Yahoo option chain (which a browser can't fetch directly because of CORS).
// All pricing / scoring happens client-side in ./lib/scanner.js.
//
// In dev, the Vite server proxies /api → http://localhost:8000.
// On Vercel, /api/* is rewritten to the Python serverless function (same origin).
// Set VITE_API_BASE at build time to point the UI at a different backend.
const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '');

/**
 * Fetch raw option chains for a list of tickers.
 * @returns { generated_at, chains: [...], notes: [...] }
 */
export async function fetchChains(tickers, { nocache = false } = {}) {
  const list = (tickers || []).map((t) => t.trim().toUpperCase()).filter(Boolean);
  if (!list.length) return { generated_at: new Date().toISOString(), chains: [], notes: [] };

  const qs = new URLSearchParams({ tickers: list.join(',') });
  if (nocache) qs.set('nocache', 'true');

  // A small watchlist resolves quickly, but cold starts + Yahoo throttling can
  // add latency — give it a generous abort window.
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120_000);
  try {
    const res = await fetch(`${API_BASE}/api/chain?${qs.toString()}`, {
      signal: controller.signal,
    });
    const ct = res.headers.get('content-type') || '';
    if (!ct.includes('application/json')) {
      throw new Error(
        'Backend returned a non-JSON response (it may be starting up). ' +
        'Please wait a moment and try again.'
      );
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(`API ${res.status}: ${body.detail || JSON.stringify(body)}`);
    }
    return res.json();
  } catch (e) {
    if (e.name === 'AbortError') {
      throw new Error(
        'The data request timed out. Live option data can be slow or ' +
        'rate-limited — try again with fewer tickers.'
      );
    }
    throw e;
  } finally {
    clearTimeout(timeout);
  }
}

// ── Shared fetch helper for the lightweight polling endpoints ────────────────
async function getJSON(path, { timeoutMs = 30_000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}${path}`, { signal: controller.signal });
    const ct = res.headers.get('content-type') || '';
    if (!ct.includes('application/json')) {
      throw new Error('Backend returned a non-JSON response (it may be starting up).');
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(`API ${res.status}: ${body.detail || JSON.stringify(body)}`);
    }
    return res.json();
  } catch (e) {
    if (e.name === 'AbortError') throw new Error('Request timed out.');
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

/** Fast last-price snapshot for a list of tickers → { quotes: {SYM: {...}}, notes }. */
export async function fetchQuotes(tickers, { nocache = false } = {}) {
  const list = (tickers || []).map((t) => t.trim().toUpperCase()).filter(Boolean);
  if (!list.length) return { quotes: {}, notes: [] };
  const qs = new URLSearchParams({ tickers: list.join(',') });
  if (nocache) qs.set('nocache', 'true');
  return getJSON(`/api/quote?${qs.toString()}`, { timeoutMs: 30_000 });
}

/** OHLC bars for a single ticker over a range → { bars: [{t,o,h,l,c,v}], ... }. */
export async function fetchHistory(ticker, range = '1d') {
  const qs = new URLSearchParams({ ticker: ticker.trim().toUpperCase(), range });
  return getJSON(`/api/history?${qs.toString()}`, { timeoutMs: 30_000 });
}

/** Recent news headlines for a list of tickers → { items: [...], notes }. */
export async function fetchNews(tickers, { limit = 20 } = {}) {
  const list = (tickers || []).map((t) => t.trim().toUpperCase()).filter(Boolean);
  if (!list.length) return { items: [], notes: [] };
  const qs = new URLSearchParams({ tickers: list.join(','), limit: String(limit) });
  return getJSON(`/api/news?${qs.toString()}`, { timeoutMs: 30_000 });
}

/** Ranked 0DTE defined-risk credit spreads (high win-rate strategy). */
export async function fetchSpreads(tickers, { accountSize = 5000, riskPct = 0.02, minPop = 0.85, maxWidth = 5 } = {}) {
  const list = (tickers || []).map((t) => t.trim().toUpperCase()).filter(Boolean);
  if (!list.length) return { spreads: [], notes: [] };
  const qs = new URLSearchParams({
    tickers: list.join(','),
    account_size: String(accountSize),
    risk_pct: String(riskPct),
    min_pop: String(minPop),
    max_width: String(maxWidth),
  });
  return getJSON(`/api/spreads?${qs.toString()}`, { timeoutMs: 120_000 });
}

/** Recent SEC EDGAR investor filings per ticker → { filings: {SYM: [...]}, notes }. */
export async function fetchFilings(tickers, { limit = 6 } = {}) {
  const list = (tickers || []).map((t) => t.trim().toUpperCase()).filter(Boolean);
  if (!list.length) return { filings: {}, notes: [] };
  const qs = new URLSearchParams({ tickers: list.join(','), limit: String(limit) });
  return getJSON(`/api/filings?${qs.toString()}`, { timeoutMs: 30_000 });
}

/** Intraday bars for one past date, for the replay practice mode. */
export async function fetchReplayDay(ticker, date) {
  const qs = new URLSearchParams({ ticker: ticker.trim().toUpperCase(), date });
  return getJSON(`/api/replay/day?${qs.toString()}`, { timeoutMs: 40_000 });
}

/** Top gainers, losers, and most-active US tickers (Alpha Vantage). */
export async function fetchMarketMovers() {
  return getJSON('/api/market/movers', { timeoutMs: 20_000 });
}

/** Upcoming earnings dates, optionally filtered to specific tickers (Alpha Vantage). */
export async function fetchEarnings(tickers = []) {
  const qs = tickers.length
    ? new URLSearchParams({ tickers: tickers.map((t) => t.toUpperCase()).join(',') })
    : null;
  return getJSON(`/api/market/earnings${qs ? '?' + qs.toString() : ''}`, { timeoutMs: 20_000 });
}
