// Thin API helper. The Vite dev server proxies /api → http://localhost:8000.
export async function fetchOpportunities(params) {
  const qs = new URLSearchParams();
  if (params.tickers) qs.set('tickers', params.tickers);
  if (params.account_size) qs.set('account_size', params.account_size);
  if (params.risk_per_trade_pct) qs.set('risk_per_trade_pct', params.risk_per_trade_pct);
  if (params.max_results) qs.set('max_results', params.max_results);
  if (params.nocache === true) qs.set('nocache', 'true');
  const res = await fetch(`/api/opportunities?${qs.toString()}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json();
}
