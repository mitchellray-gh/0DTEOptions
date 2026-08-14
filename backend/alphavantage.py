"""Alpha Vantage API client — free-tier endpoints only.

Endpoints used (25 req/day free limit; all are genuinely free with this key):
  NEWS_SENTIMENT    — real news articles with ticker relevance + sentiment scores.
                      Replaces the Yahoo search-based news feed.
  TOP_GAINERS_LOSERS — EOD top 20 gainers/losers/most-active in the US market.
  EARNINGS_CALENDAR  — upcoming earnings dates for any ticker (CSV, 3 months).

The key is loaded from the AV_API_KEY environment variable (or the .env file in
the repo root, which is gitignored). Never hardcode it.
"""
from __future__ import annotations

import csv
import io
import logging
import os
import threading
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)

_BASE = "https://www.alphavantage.co/query"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# ── Caches (reduce the 25 req/day budget) ────────────────────────────────────
_news_cache: dict[str, tuple[float, list]] = {}
_NEWS_TTL = 600.0       # 10 min — news changes infrequently

_earnings_cache: tuple[float, list] | None = None
_EARNINGS_TTL = 3600.0  # 1 hr

_movers_cache: tuple[float, dict] | None = None
_MOVERS_TTL = 1800.0    # 30 min — changes slowly during the day

_lock = threading.Lock()


def _api_key() -> str | None:
    key = os.environ.get("AV_API_KEY", "").strip()
    if key:
        return key
    # Fall back to reading the .env file if not set in env.
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("AV_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None


def _get(params: dict, timeout: int = 20) -> dict | None:
    key = _api_key()
    if not key:
        log.warning("AV_API_KEY not set — skipping Alpha Vantage request")
        return None
    params["apikey"] = key
    try:
        r = requests.get(_BASE, params=params,
                         headers={"User-Agent": _UA}, timeout=timeout)
        j = r.json()
    except Exception as exc:
        log.warning("Alpha Vantage request failed: %s", exc)
        return None
    if "Information" in j or "Note" in j:
        log.warning("Alpha Vantage rate-limited or premium gated: %s",
                    j.get("Information") or j.get("Note"))
        return None
    return j


def _get_csv(params: dict, timeout: int = 20) -> list[dict]:
    key = _api_key()
    if not key:
        return []
    params["apikey"] = key
    try:
        r = requests.get(_BASE, params=params,
                         headers={"User-Agent": _UA}, timeout=timeout)
        return list(csv.DictReader(io.StringIO(r.text)))
    except Exception as exc:
        log.warning("Alpha Vantage CSV request failed: %s", exc)
        return []


# ── Public API ────────────────────────────────────────────────────────────────

def news_sentiment(tickers: list[str], limit: int = 20) -> list[dict]:
    """Return news articles for the given tickers with AV sentiment scores.

    Each item::
        {title, url, time_published, source, summary, banner_image,
         overall_sentiment_label, overall_sentiment_score,
         ticker_sentiment: [{ticker, relevance_score, ticker_sentiment_score,
                             ticker_sentiment_label}]}

    Caches per ticker-set for 10 minutes. Returns [] on key/limit errors.
    """
    sym_key = ",".join(sorted(t.upper() for t in tickers))
    with _lock:
        cached = _news_cache.get(sym_key)
        if cached and (time.time() - cached[0]) < _NEWS_TTL:
            return cached[1]

    j = _get({"function": "NEWS_SENTIMENT",
               "tickers": sym_key,
               "limit": str(limit),
               "sort": "LATEST"})
    items: list[dict] = []
    if j:
        feed = j.get("feed") or []
        for a in feed:
            items.append({
                "title": a.get("title", ""),
                "url": a.get("url", ""),
                "time_published": a.get("time_published", ""),
                "source": a.get("source", ""),
                "summary": a.get("summary", ""),
                "banner_image": a.get("banner_image"),
                "overall_sentiment_label": a.get("overall_sentiment_label", ""),
                "overall_sentiment_score": a.get("overall_sentiment_score", 0),
                "sentiment_label": a.get("overall_sentiment_label", ""),
                "sentiment_score": a.get("overall_sentiment_score", 0),
                "ticker_sentiment": a.get("ticker_sentiment", []),
            })
    with _lock:
        _news_cache[sym_key] = (time.time(), items)
    return items


def top_gainers_losers() -> dict:
    """Return today's top 20 gainers, losers, and most-active US tickers.

    Shape: {last_updated, top_gainers: [...], top_losers: [...],
            most_actively_traded: [...]}
    Each entry: {ticker, price, change_amount, change_percentage, volume}
    """
    global _movers_cache
    with _lock:
        if _movers_cache and (time.time() - _movers_cache[0]) < _MOVERS_TTL:
            return _movers_cache[1]

    j = _get({"function": "TOP_GAINERS_LOSERS"})
    result: dict = {}
    if j:
        result = {
            "last_updated": j.get("last_updated", ""),
            "top_gainers": j.get("top_gainers", [])[:20],
            "top_losers": j.get("top_losers", [])[:20],
            "most_actively_traded": j.get("most_actively_traded", [])[:20],
        }
    with _lock:
        _movers_cache = (time.time(), result)
    return result


def earnings_calendar(horizon: str = "3month") -> list[dict]:
    """Upcoming earnings dates for the next 3 months (full market).

    Each row: {symbol, name, reportDate, fiscalDateEnding, estimate,
               currency, timeOfTheDay}
    """
    global _earnings_cache
    with _lock:
        if _earnings_cache and (time.time() - _earnings_cache[0]) < _EARNINGS_TTL:
            return _earnings_cache[1]

    rows = _get_csv({"function": "EARNINGS_CALENDAR", "horizon": horizon})
    with _lock:
        _earnings_cache = (time.time(), rows)
    return rows


def earnings_for_tickers(tickers: list[str]) -> dict[str, list[dict]]:
    """Return upcoming earnings filtered to the given ticker list.

    Uses the cached full calendar — doesn't cost an extra API call.
    """
    syms = {t.upper() for t in tickers}
    out: dict[str, list[dict]] = {s: [] for s in syms}
    for row in earnings_calendar():
        s = (row.get("symbol") or "").upper()
        if s in syms:
            out[s].append(row)
    return out
