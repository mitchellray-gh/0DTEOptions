import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Routes, Route, useLocation, Outlet } from 'react-router-dom';
import BottomNav from './components/BottomNav.jsx';
import ErrorBoundary from './components/ErrorBoundary.jsx';
import { useLiveQuotes } from './lib/useLiveQuotes.js';
import InvestPage from './pages/InvestPage.jsx';
import InstrumentPage from './pages/InstrumentPage.jsx';
import SpreadsPage from './pages/SpreadsPage.jsx';
import PracticePage from './pages/PracticePage.jsx';
import LearnPage from './pages/LearnPage.jsx';
import MethodologyPage from './pages/MethodologyPage.jsx';
import DiscoverPage from './pages/DiscoverPage.jsx';
import ProfilePage from './pages/ProfilePage.jsx';

const LS_WATCHLIST = 'zdte.watchlist';
const LS_SETTINGS = 'zdte.settings';
const DEFAULT_WATCHLIST = ['SPY', 'QQQ', 'IWM', 'DIA', 'NVDA'];
const DEFAULT_SETTINGS = { accountSize: 5000, riskPct: 2, minEdge: 5, type: 'all', maxResults: 50 };

function loadJSON(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) ?? fallback) : fallback;
  } catch {
    return fallback;
  }
}

const TITLES = {
  '/': ['Invest', 'Live 0DTE opportunities'],
  '/instrument': ['Invest', 'Instrument detail'],
  '/spreads': ['Spreads', 'High win-rate credit spreads'],
  '/practice': ['Practice', 'Paper trade & replay'],
  '/learn': ['Learn', 'Master 0DTE options'],
  '/methodology': ['Methodology', 'Data & audit transparency'],
  '/discover': ['Discover', 'News & analytics'],
  '/profile': ['Profile', 'Your account'],
};

function Shell({ ctx }) {
  const location = useLocation();
  const { fresh, updatedAt } = ctx;
  const base = '/' + (location.pathname.split('/')[1] || '');
  const [title, sub] = TITLES[base] || ['0DTE Trainer', ''];
  const stamp = updatedAt ? updatedAt.toLocaleTimeString() : '—';

  return (
    <div className="rh-shell">
      <div className="rh-topbar">
        <div>
          <h1 className="rh-title">{title}</h1>
          <div className="rh-sub">{sub}</div>
        </div>
        <span className={`rh-live${fresh ? '' : ' stale'}`} title={`Last update ${stamp}`}>
          <span className="dot" /> {fresh ? 'LIVE' : 'idle'} · {stamp}
        </span>
      </div>
      <ErrorBoundary routeKey={location.pathname}>
        <Outlet context={ctx} />
      </ErrorBoundary>
      <BottomNav />
    </div>
  );
}

export default function App() {
  const [watchlist, setWatchlist] = useState(() => {
    const wl = loadJSON(LS_WATCHLIST, DEFAULT_WATCHLIST);
    return Array.isArray(wl) && wl.length ? wl : DEFAULT_WATCHLIST;
  });
  const [settings, setSettings] = useState(() => ({ ...DEFAULT_SETTINGS, ...loadJSON(LS_SETTINGS, {}) }));

  useEffect(() => { localStorage.setItem(LS_WATCHLIST, JSON.stringify(watchlist)); }, [watchlist]);
  useEffect(() => { localStorage.setItem(LS_SETTINGS, JSON.stringify(settings)); }, [settings]);

  const { quotes, updatedAt, fresh, refresh } = useLiveQuotes(watchlist, { intervalMs: 12_000 });

  const addTicker = useCallback((raw) => {
    const t = String(raw || '').trim().toUpperCase();
    if (!/^[A-Z][A-Z.\-]{0,5}$/.test(t)) return 'Enter a valid symbol, e.g. AAPL';
    if (watchlist.includes(t)) return `${t} is already tracked`;
    if (watchlist.length >= 25) return 'Watchlist is full (25 max)';
    setWatchlist((w) => [...w, t]);
    return null;
  }, [watchlist]);

  const removeTicker = useCallback((t) => setWatchlist((w) => w.filter((x) => x !== t)), []);

  const ctx = useMemo(() => ({
    watchlist, setWatchlist, addTicker, removeTicker,
    settings, setSettings,
    quotes, updatedAt, fresh, refreshQuotes: refresh,
  }), [watchlist, setWatchlist, addTicker, removeTicker, settings, quotes, updatedAt, fresh, refresh]);

  return (
    <Routes>
      <Route element={<Shell ctx={ctx} />}>
        <Route path="/" element={<InvestPage />} />
        <Route path="/instrument/:symbol" element={<InstrumentPage />} />
        <Route path="/spreads" element={<SpreadsPage />} />
        <Route path="/practice" element={<PracticePage />} />
        <Route path="/learn" element={<LearnPage />} />
        <Route path="/methodology" element={<MethodologyPage />} />
        <Route path="/discover" element={<DiscoverPage />} />
        <Route path="/profile" element={<ProfilePage />} />
      </Route>
    </Routes>
  );
}
