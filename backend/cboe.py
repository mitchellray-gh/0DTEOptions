"""CBOE delayed-quote client — real exchange option data (no API key).

CBOE publishes a free, ~15-minute-delayed JSON feed with the FULL option chain
for liquid symbols, including real **bid/ask, IV, and greeks** (delta, gamma,
theta, vega) straight from the exchange. That's richer and more reliable than
yfinance's scraped chain, so the app uses CBOE as the PRIMARY chain source and
falls back to yfinance (via ``backend.yahoo``) only when CBOE has no data for a
symbol.

Endpoint: https://cdn.cboe.com/api/global/delayed_quotes/options/{SYMBOL}.json
Index products use an underscore prefix (e.g. ``_SPX``); we try both.
"""
from __future__ import annotations

import datetime as _dt
import logging
import re

import requests

log = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_BASE = "https://cdn.cboe.com/api/global/delayed_quotes/options/{}.json"

# OCC-style contract symbol: ROOT + YYMMDD + C/P + strike*1000 (8 digits)
_SYM_RE = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")


def _parse_symbol(sym: str):
    m = _SYM_RE.match(sym)
    if not m:
        return None
    _root, ymd, cp, strike = m.groups()
    try:
        d = _dt.date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:6]))
    except ValueError:
        return None
    return d, ("call" if cp == "C" else "put"), int(strike) / 1000.0


def _fetch_raw(symbol: str) -> dict | None:
    sym = symbol.strip().upper()
    for candidate in (sym, f"_{sym}"):
        try:
            r = requests.get(_BASE.format(candidate),
                             headers={"User-Agent": _UA}, timeout=20)
        except requests.RequestException as exc:
            log.warning("CBOE fetch failed for %s: %s", candidate, exc)
            continue
        if r.status_code == 200:
            try:
                j = r.json()
            except ValueError:
                continue
            if (j.get("data") or {}).get("options"):
                return j["data"]
    return None


def _pick_expiry(expiries: list[_dt.date], today: _dt.date) -> _dt.date | None:
    """Nearest expiry that is today or within the next 3 days (0DTE-first)."""
    best = None
    for d in expiries:
        days = (d - today).days
        if 0 <= days <= 3 and (best is None or days < (best - today).days):
            best = d
    return best


def fetch_chain(symbol: str) -> dict | None:
    """Return a 0DTE/near-dated chain from CBOE in the app's chain shape.

    ``{underlying, spot, expiration, minutes_to_expiry, calls[], puts[]}`` with
    real exchange bid/ask/IV per contract, or ``None`` if CBOE has no usable
    data (caller falls back to yfinance).
    """
    data = _fetch_raw(symbol)
    if not data:
        return None

    spot = 0.0
    for key in ("current_price", "close", "prev_day_close"):
        try:
            v = float(data.get(key) or 0.0)
        except (TypeError, ValueError):
            v = 0.0
        if v > 0:
            spot = v
            break
    if spot <= 0:
        return None

    options = data.get("options") or []
    parsed: list[tuple[_dt.date, str, float, dict]] = []
    for o in options:
        p = _parse_symbol(str(o.get("option", "")))
        if p:
            parsed.append((p[0], p[1], p[2], o))
    if not parsed:
        return None

    today = _dt.datetime.now(_dt.timezone.utc).date()
    expiry = _pick_expiry(sorted({p[0] for p in parsed}), today)
    if expiry is None:
        return None

    def _row(o: dict, strike: float) -> dict:
        def f(k):
            try:
                return float(o.get(k) or 0.0)
            except (TypeError, ValueError):
                return 0.0
        return {
            "contractSymbol": str(o.get("option", "")),
            "strike": strike,
            "bid": f("bid"),
            "ask": f("ask"),
            "lastPrice": f("last_trade_price"),
            "volume": int(f("volume")),
            "openInterest": int(f("open_interest")),
            "impliedVolatility": f("iv"),
            # Real exchange greeks — bonus fields the app can display.
            "delta": f("delta"),
            "gamma": f("gamma"),
            "theta": f("theta"),
            "vega": f("vega"),
        }

    calls, puts = [], []
    for d, otype, strike, o in parsed:
        if d != expiry:
            continue
        (calls if otype == "call" else puts).append(_row(o, strike))
    if not calls and not puts:
        return None

    # Minutes to 16:00 ET on the expiry date (UTC-4 EDT approximation).
    close_utc = _dt.datetime(expiry.year, expiry.month, expiry.day, 20, 0, 0,
                             tzinfo=_dt.timezone.utc)
    minutes = max(int((close_utc - _dt.datetime.now(_dt.timezone.utc))
                      .total_seconds() // 60), 1)

    calls.sort(key=lambda r: r["strike"])
    puts.sort(key=lambda r: r["strike"])
    return {
        "underlying": symbol.strip().upper(),
        "spot": round(spot, 4),
        "expiration": expiry.isoformat(),
        "minutes_to_expiry": minutes,
        "calls": calls,
        "puts": puts,
        "source": "cboe",
    }
