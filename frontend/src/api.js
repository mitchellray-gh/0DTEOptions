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
