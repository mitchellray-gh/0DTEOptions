"""SEC EDGAR investor-filings client.

Surfaces official investor documentation (10-K annual reports, 10-Q quarterlies,
8-K material events, proxy statements, prospectuses, etc.) for a ticker, so the
news feed can link to primary-source documents alongside headlines.

EDGAR is a free public API. Its fair-access policy REQUIRES a descriptive
``User-Agent`` with contact info; datacenters (incl. Vercel) are allowed.
"""
from __future__ import annotations

import logging
import threading
import time

import requests

log = logging.getLogger(__name__)

_UA = "0DTEOptions educational trainer (contact: user@example.com)"
_HEADERS = {"User-Agent": _UA, "Accept-Encoding": "gzip, deflate"}

# Material investor documents worth surfacing (skip insider Form 3/4/5, 13G, etc.)
_MATERIAL_FORMS = {
    "10-K": "Annual report",
    "10-K/A": "Annual report (amended)",
    "10-Q": "Quarterly report",
    "10-Q/A": "Quarterly report (amended)",
    "8-K": "Material event",
    "8-K/A": "Material event (amended)",
    "DEF 14A": "Proxy statement",
    "DEFA14A": "Proxy statement",
    "S-1": "Registration / prospectus",
    "S-1/A": "Registration / prospectus (amended)",
    "424B2": "Prospectus",
    "424B3": "Prospectus",
    "424B5": "Prospectus",
    "20-F": "Annual report (foreign)",
    "6-K": "Foreign issuer report",
    "40-F": "Annual report (Canadian)",
    "N-CSR": "Certified shareholder report",
    "N-CSRS": "Semi-annual shareholder report",
    "497": "Fund prospectus",
    "497K": "Fund summary prospectus",
}

_lock = threading.Lock()
_cik_map: dict[str, str] | None = None
_cik_ts: float = 0.0
_CIK_TTL = 24 * 3600.0  # refresh the ticker→CIK map daily


def _load_cik_map(force: bool = False) -> dict[str, str]:
    """Fetch and cache SEC's ticker→CIK mapping (~800KB, refreshed daily)."""
    global _cik_map, _cik_ts
    with _lock:
        if _cik_map is not None and not force and (time.time() - _cik_ts) < _CIK_TTL:
            return _cik_map
        try:
            r = requests.get(
                "https://www.sec.gov/files/company_tickers.json",
                headers=_HEADERS, timeout=20,
            )
            r.raise_for_status()
            data = r.json()
            _cik_map = {
                str(v["ticker"]).upper(): str(v["cik_str"]).zfill(10)
                for v in data.values()
                if v.get("ticker")
            }
            _cik_ts = time.time()
        except Exception as exc:  # noqa: BLE001
            log.warning("EDGAR ticker map fetch failed: %s", exc)
            if _cik_map is None:
                _cik_map = {}
        return _cik_map


def filings(ticker: str, limit: int = 6) -> list[dict]:
    """Return recent material investor filings for a ticker.

    Each item: ``{form, description, filed, title, link}`` where ``link`` points
    to the primary document on EDGAR. Returns ``[]`` (never raises) when the
    ticker isn't a registered filer (e.g. many ETFs) or EDGAR is unavailable.
    """
    sym = (ticker or "").upper().strip()
    if not sym:
        return []
    cik = _load_cik_map().get(sym)
    if not cik:
        return []

    try:
        r = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=_HEADERS, timeout=20,
        )
        r.raise_for_status()
        j = r.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("EDGAR submissions fetch failed for %s: %s", sym, exc)
        return []

    recent = (j.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accessions = recent.get("accessionNumber") or []
    primaries = recent.get("primaryDocument") or []
    docs = recent.get("primaryDocDescription") or []

    cik_int = str(int(cik))  # EDGAR archive path uses the CIK without zero-padding
    out: list[dict] = []
    for i, form in enumerate(forms):
        if form not in _MATERIAL_FORMS:
            continue
        acc = accessions[i] if i < len(accessions) else ""
        acc_nodash = acc.replace("-", "")
        primary = primaries[i] if i < len(primaries) else ""
        if not acc_nodash:
            continue
        if primary:
            link = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{primary}"
        else:
            link = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/"
        out.append({
            "form": form,
            "description": _MATERIAL_FORMS.get(form, form),
            "filed": dates[i] if i < len(dates) else None,
            "title": (docs[i] if i < len(docs) and docs[i] else _MATERIAL_FORMS.get(form, form)),
            "link": link,
        })
        if len(out) >= limit:
            break
    return out
