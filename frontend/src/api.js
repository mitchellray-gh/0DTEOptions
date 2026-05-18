// Thin API helper. The Vite dev server proxies /api → http://localhost:8000.
export async function fetchOpportunities(params) {
  const qs = new URLSearchParams();
  if (params.tickers) qs.set('tickers', params.tickers);
  if (params.account_size) qs.set('account_size', params.account_size);
  if (params.risk_per_trade_pct) qs.set('risk_per_trade_pct', params.risk_per_trade_pct);
  if (params.max_results) qs.set('max_results', params.max_results);
  if (params.nocache === true) qs.set('nocache', 'true');
  // SP500 scans can take several minutes; use AbortController with a generous timeout
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 600_000); // 10 min
  try {
    const res = await fetch(`/api/opportunities?${qs.toString()}`, {
      signal: controller.signal,
    });
    const ct = res.headers.get('content-type') || '';
    // Guard against proxy returning HTML (e.g. during backend reload)
    if (!ct.includes('application/json')) {
      throw new Error(
        'Backend returned non-JSON response (it may be restarting). ' +
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
        'The scan is taking longer than expected. ' +
        'SP500 scans can take up to 10 minutes — please try again.'
      );
    }
    throw e;
  } finally {
    clearTimeout(timeout);
  }
}
