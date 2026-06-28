"""Fetch and cache the current S&P 500 constituent tickers.

Primary source: Wikipedia's "List of S&P 500 companies" page.
Fallback: a hardcoded snapshot (updated May 2026) so the scanner
always works even if Wikipedia is unreachable.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)

_sp500_cache: Optional[list[str]] = None
_sp500_cache_ts: float = 0.0
_CACHE_TTL = 86_400  # refresh once per day

# URL for the Wikipedia table
_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def fetch_sp500_tickers(force: bool = False) -> list[str]:
    """Return sorted list of S&P 500 ticker symbols.

    Tries Wikipedia first; falls back to a hardcoded snapshot.
    Results are cached for 24 hours.
    """
    global _sp500_cache, _sp500_cache_ts

    now = time.time()
    if not force and _sp500_cache and (now - _sp500_cache_ts) < _CACHE_TTL:
        return _sp500_cache

    tickers = _fetch_from_wikipedia()
    if not tickers:
        log.warning("Wikipedia fetch failed; using hardcoded S&P 500 snapshot")
        tickers = _HARDCODED_SP500

    _sp500_cache = sorted(set(t for t in tickers if t not in _SKIP_TICKERS))
    _sp500_cache_ts = now
    log.info("S&P 500 tickers loaded: %d symbols (%d skipped as delisted)",
             len(_sp500_cache), len(_SKIP_TICKERS))
    return _sp500_cache


def _fetch_from_wikipedia() -> list[str] | None:
    try:
        tables = pd.read_html(_WIKI_URL, header=0, flavor="bs4")
        df = tables[0]
        # The ticker column is usually "Symbol"
        col = None
        for c in df.columns:
            if "symbol" in c.lower() or "ticker" in c.lower():
                col = c
                break
        if col is None:
            return None
        raw = df[col].dropna().tolist()
        # Wikipedia uses dots (BRK.B) but Yahoo uses dashes (BRK-B)
        return [str(t).strip().replace(".", "-") for t in raw if str(t).strip()]
    except Exception as exc:
        log.warning("Failed to scrape S&P 500 from Wikipedia: %s", exc)
        return None


# Hardcoded fallback — a snapshot of the 503 tickers (some share classes)
# as of May 2026. Yahoo-style notation (BRK-B not BRK.B).

# Tickers known to be delisted / merged / defunct — skip them to save time.
_SKIP_TICKERS = frozenset([
    "ATVI",   # Acquired by Microsoft
    "CTRA",   # Delisted
    "SIVB",   # Collapsed (Silicon Valley Bank)
    "FRC",    # Collapsed (First Republic)
    "SBNY",   # Collapsed (Signature Bank)
    "DISH",   # Merged with EchoStar
    "TWTR",   # Taken private
    "LUMN",   # Restructured
    "DXC",    # Removed from S&P
    "FLT",    # Rebranded to Corpay (CPAY)
    "FBHS",   # Renamed / restructured
    "PEAK",   # Renamed to Healthpeak (DOC)
    "CTLT",   # Acquired by Novo Nordisk
    "ANSS",   # Acquired by Synopsys
    "DFS",    # Acquired by Capital One
])

_HARDCODED_SP500 = [
    "AAPL", "ABBV", "ABT", "ACN", "ADBE", "ADI", "ADM", "ADP", "ADSK", "AEE",
    "AEP", "AES", "AFL", "AIG", "AIZ", "AJG", "AKAM", "ALB", "ALGN", "ALK",
    "ALL", "ALLE", "AMAT", "AMCR", "AMD", "AME", "AMGN", "AMP", "AMT", "AMZN",
    "ANET", "ANSS", "AON", "AOS", "APA", "APD", "APH", "APTV", "ARE", "ATO",
    "ATVI", "AVB", "AVGO", "AVY", "AWK", "AXP", "AZO", "BA", "BAC", "BAX",
    "BBWI", "BBY", "BDX", "BEN", "BF-B", "BG", "BIIB", "BIO", "BK", "BKNG",
    "BKR", "BLK", "BMY", "BR", "BRK-B", "BRO", "BSX", "BWA", "BXP", "C",
    "CAG", "CAH", "CARR", "CAT", "CB", "CBOE", "CBRE", "CCI", "CCL", "CDAY",
    "CDNS", "CDW", "CE", "CEG", "CF", "CFG", "CHD", "CHRW", "CHTR", "CI",
    "CINF", "CL", "CLX", "CMA", "CMCSA", "CME", "CMG", "CMI", "CMS", "CNC",
    "CNP", "COF", "COO", "COP", "COST", "CPB", "CPRT", "CPT", "CRL", "CRM",
    "CSCO", "CSGP", "CSX", "CTAS", "CTLT", "CTRA", "CTSH", "CTVA", "CVS",
    "CVX", "CZR", "D", "DAL", "DD", "DE", "DFS", "DG", "DGX", "DHI", "DHR",
    "DIS", "DISH", "DLTR", "DOV", "DOW", "DPZ", "DRI", "DTE", "DUK", "DVA",
    "DVN", "DXC", "DXCM", "EA", "EBAY", "ECL", "ED", "EFX", "EIX", "EL",
    "EMN", "EMR", "ENPH", "EOG", "EPAM", "EQIX", "EQR", "EQT", "ES", "ESS",
    "ETN", "ETR", "ETSY", "EVRG", "EW", "EXC", "EXPD", "EXPE", "EXR", "F",
    "FANG", "FAST", "FBHS", "FCX", "FDS", "FDX", "FE", "FFIV", "FIS", "FISV",
    "FITB", "FLT", "FMC", "FOX", "FOXA", "FRC", "FRT", "FTNT", "FTV", "GD",
    "GE", "GILD", "GIS", "GL", "GLW", "GM", "GNRC", "GOOG", "GOOGL", "GPC",
    "GPN", "GRMN", "GS", "GWW", "HAL", "HAS", "HBAN", "HCA", "HD", "PEAK",
    "HES", "HIG", "HII", "HLT", "HOLX", "HON", "HPE", "HPQ", "HRL", "HSIC",
    "HST", "HSY", "HUM", "HWM", "IBM", "ICE", "IDXX", "IEX", "IFF", "ILMN",
    "INCY", "INTC", "INTU", "INVH", "IP", "IPG", "IQV", "IR", "IRM", "ISRG",
    "IT", "ITW", "IVZ", "J", "JBHT", "JCI", "JKHY", "JNJ", "JNPR", "JPM",
    "K", "KDP", "KEY", "KEYS", "KHC", "KIM", "KLAC", "KMB", "KMI", "KMX",
    "KO", "KR", "L", "LDOS", "LEN", "LH", "LHX", "LIN", "LKQ", "LLY",
    "LMT", "LNC", "LNT", "LOW", "LRCX", "LUMN", "LUV", "LVS", "LW", "LYB",
    "LYV", "MA", "MAA", "MAR", "MAS", "MCD", "MCHP", "MCK", "MCO", "MDLZ",
    "MDT", "MET", "META", "MGM", "MHK", "MKC", "MKTX", "MLM", "MMC", "MMM",
    "MNST", "MO", "MOH", "MOS", "MPC", "MPWR", "MRK", "MRNA", "MRO", "MS",
    "MSCI", "MSFT", "MSI", "MTB", "MTCH", "MTD", "MU", "NCLH", "NDAQ", "NDSN",
    "NEE", "NEM", "NFLX", "NI", "NKE", "NOC", "NOW", "NRG", "NSC", "NTAP",
    "NTRS", "NUE", "NVDA", "NVR", "NWL", "NWS", "NWSA", "NXPI", "O", "ODFL",
    "OGN", "OKE", "OMC", "ON", "ORCL", "ORLY", "OTIS", "OXY", "PARA", "PAYC",
    "PAYX", "PCAR", "PCG", "PEAK", "PEG", "PEP", "PFE", "PFG", "PG", "PGR",
    "PH", "PHM", "PKG", "PKI", "PLD", "PM", "PNC", "PNR", "PNW", "POOL",
    "PPG", "PPL", "PRU", "PSA", "PSX", "PTC", "PVH", "PWR", "PXD", "PYPL",
    "QCOM", "QRVO", "RCL", "RE", "REG", "REGN", "RF", "RHI", "RJF", "RL",
    "RMD", "ROK", "ROL", "ROP", "ROST", "RSG", "RTX", "SBAC", "SBNY", "SBUX",
    "SCHW", "SEE", "SHW", "SIVB", "SJM", "SLB", "SNA", "SNPS", "SO", "SPG",
    "SPGI", "SRE", "STE", "STT", "STX", "STZ", "SWK", "SWKS", "SYF", "SYK",
    "SYY", "T", "TAP", "TDG", "TDY", "TECH", "TEL", "TER", "TFC", "TFX",
    "TGT", "TMO", "TMUS", "TPR", "TRGP", "TRMB", "TROW", "TRV", "TSCO",
    "TSLA", "TSN", "TT", "TTWO", "TXN", "TXT", "TYL", "UAL", "UDR", "UHS",
    "ULTA", "UNH", "UNP", "UPS", "URI", "USB", "V", "VFC", "VICI", "VLO",
    "VMC", "VNO", "VRSK", "VRSN", "VRTX", "VTR", "VTRS", "VZ", "WAB", "WAT",
    "WBA", "WBD", "WDC", "WEC", "WELL", "WFC", "WHR", "WM", "WMB", "WMT",
    "WRB", "WRK", "WST", "WTW", "WY", "WYNN", "XEL", "XOM", "XRAY", "XYL",
    "YUM", "ZBH", "ZBRA", "ZION", "ZTS",
]
