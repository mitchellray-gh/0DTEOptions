"""Direct Yahoo Finance JSON client.

yfinance's default request path is frequently blocked from datacenters (e.g.
Vercel serverless), which returns empty data. Yahoo's public JSON endpoints work
reliably when called with a browser User-Agent plus the cookie/crumb handshake,
so this module talks to them directly:

  * ``chart``   — /v8/finance/chart/{symbol}   (quotes + OHLC bars; no crumb)
  * ``options`` — /v7/finance/options/{symbol}  (option chains; needs a crumb)
  * ``search``  — /v1/finance/search            (news headlines; no crumb)

Everything here is delayed market data for an educational tool. On a corporate
network that MITM-inspects TLS, set ``REQUESTS_CA_BUNDLE`` to your trusted-root
PEM so ``requests`` can validate the chain (Vercel doesn't need this).
"""
from __future__ import annotations

import logging
import threading
import time

import requests

log = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_Q1 = "https://query1.finance.yahoo.com"
_Q2 = "https://query2.finance.yahoo.com"

_lock = threading.Lock()
_session: requests.Session | None = None
_crumb: str = ""
_crumb_ts: float = 0.0
_CRUMB_TTL = 1800.0  # refresh the cookie/crumb every 30 min


def _build_session() -> tuple[requests.Session, str]:
    """Create a session with a browser UA and fetch a fresh cookie + crumb."""
    s = requests.Session()
    s.headers.update({"User-Agent": _UA, "Accept": "application/json,text/plain,*/*"})
    crumb = ""
    try:
        # Seed the A3 consent cookie, then exchange it for a crumb.
        s.get("https://fc.yahoo.com", timeout=10)
    except requests.RequestException as exc:  # pragma: no cover - network
        log.warning("Yahoo cookie seed failed: %s", exc)
    try:
        r = s.get(f"{_Q1}/v1/test/getcrumb", timeout=10)
        if r.ok and r.text and "<" not in r.text:
            crumb = r.text.strip()
    except requests.RequestException as exc:  # pragma: no cover - network
        log.warning("Yahoo crumb fetch failed: %s", exc)
    return s, crumb


def _get_session(force: bool = False) -> tuple[requests.Session, str]:
    global _session, _crumb, _crumb_ts
    with _lock:
        fresh = (time.time() - _crumb_ts) < _CRUMB_TTL
        if _session is not None and _crumb and fresh and not force:
            return _session, _crumb
        _session, _crumb = _build_session()
        _crumb_ts = time.time()
        return _session, _crumb


def _get_json(url: str, params: dict | None = None, use_crumb: bool = False) -> dict:
    """GET a Yahoo JSON endpoint, refreshing the crumb once on a 401."""
    s, crumb = _get_session()
    p = dict(params or {})
    if use_crumb and crumb:
        p["crumb"] = crumb
    r = s.get(url, params=p, timeout=20)
    if r.status_code in (401, 403) and use_crumb:
        s, crumb = _get_session(force=True)
        p["crumb"] = crumb
        r = s.get(url, params=p, timeout=20)
    r.raise_for_status()
    return r.json()


# ── Public API ───────────────────────────────────────────────────────────────

def chart(symbol: str, range_: str = "1d", interval: str = "5m") -> dict:
    """Return the raw Yahoo chart payload's first result (meta + quote bars)."""
    j = _get_json(
        f"{_Q1}/v8/finance/chart/{symbol}",
        {"range": range_, "interval": interval, "includePrePost": "false"},
    )
    results = (j.get("chart") or {}).get("result") or []
    if not results:
        err = (j.get("chart") or {}).get("error")
        raise ValueError(f"No chart data for {symbol}: {err}")
    return results[0]


def chart_period(symbol: str, period1: int, period2: int, interval: str) -> dict:
    """Chart payload for an explicit epoch-second window (for a past date)."""
    j = _get_json(
        f"{_Q1}/v8/finance/chart/{symbol}",
        {"period1": period1, "period2": period2, "interval": interval,
         "includePrePost": "false"},
    )
    results = (j.get("chart") or {}).get("result") or []
    if not results:
        raise ValueError(f"No chart data for {symbol}")
    return results[0]


def options(symbol: str, date_epoch: int | None = None) -> dict:
    """Return the first Yahoo option-chain result (needs the crumb)."""
    params = {"date": date_epoch} if date_epoch else None
    j = _get_json(f"{_Q1}/v7/finance/options/{symbol}", params, use_crumb=True)
    results = (j.get("optionChain") or {}).get("result") or []
    if not results:
        err = (j.get("optionChain") or {}).get("error")
        raise ValueError(f"No option chain for {symbol}: {err}")
    return results[0]


def quotes(symbols: list[str]) -> dict[str, dict]:
    """Batch last-price snapshot for many symbols in ONE request (needs crumb).

    Returns ``{SYM: {price, prev_close}}``. Far faster than one chart request
    per ticker — the whole watchlist resolves in a single round-trip.
    """
    if not symbols:
        return {}
    j = _get_json(
        f"{_Q1}/v7/finance/quote",
        {"symbols": ",".join(symbols)},
        use_crumb=True,
    )
    out: dict[str, dict] = {}
    for q in (j.get("quoteResponse") or {}).get("result") or []:
        sym = q.get("symbol")
        price = q.get("regularMarketPrice")
        if not sym or price is None:
            continue
        prev = q.get("regularMarketPreviousClose") or q.get("chartPreviousClose")
        out[str(sym)] = {
            "price": float(price),
            "prev_close": float(prev) if prev is not None else float(price),
        }
    return out


def search_news(symbol: str, count: int = 10) -> list[dict]:
    """Return recent news items for a symbol via the search endpoint."""
    j = _get_json(
        f"{_Q1}/v1/finance/search",
        {"q": symbol, "quotesCount": 0, "newsCount": count,
         "enableFuzzyQuery": "false"},
    )
    return j.get("news") or []


def bars_from_chart(result: dict) -> list[dict]:
    """Convert a chart result into ``[{t,o,h,l,c,v}]`` (ISO-UTC timestamps)."""
    import datetime as _dt

    ts = result.get("timestamp") or []
    quote = (((result.get("indicators") or {}).get("quote") or [{}])[0]) or {}
    opens, highs = quote.get("open") or [], quote.get("high") or []
    lows, closes = quote.get("low") or [], quote.get("close") or []
    vols = quote.get("volume") or []
    bars: list[dict] = []
    for i, t in enumerate(ts):
        c = closes[i] if i < len(closes) else None
        if c is None:
            continue
        iso = _dt.datetime.fromtimestamp(t, tz=_dt.timezone.utc).isoformat()
        bars.append({
            "t": iso,
            "o": float(opens[i]) if i < len(opens) and opens[i] is not None else float(c),
            "h": float(highs[i]) if i < len(highs) and highs[i] is not None else float(c),
            "l": float(lows[i]) if i < len(lows) and lows[i] is not None else float(c),
            "c": float(c),
            "v": int(vols[i]) if i < len(vols) and vols[i] is not None else 0,
        })
    return bars
