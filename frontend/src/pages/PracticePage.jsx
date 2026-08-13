import React, { useEffect, useMemo, useRef, useState } from 'react';
import { fetchReplayDay } from '../api.js';
import { scanChains } from '../lib/scanner.js';
import { buildSyntheticChain } from '../lib/replaySim.js';
import {
  loadPaper, resetPaper, sellToClose, buyToOpen, markPosition, summarize, STARTING_CASH,
} from '../lib/paper.js';
import { fmt$ } from '../lib/format.js';

const pctSigned = (x) => `${x >= 0 ? '+' : ''}${(x * 100).toFixed(1)}%`;

function minutesLeftFor(pos) {
  if (pos.minutesToExpiryAtEntry == null) return 60;
  const elapsedMs = Date.now() - new Date(pos.entryTime).getTime();
  return Math.max(pos.minutesToExpiryAtEntry - elapsedMs / 60000, 0);
}

export default function PracticePage() {
  const [view, setView] = useState('portfolio');
  return (
    <div className="rh-page">
      <div className="rh-seg" style={{ marginBottom: 14 }}>
        <button className={view === 'portfolio' ? 'active-buy' : ''} onClick={() => setView('portfolio')}>Portfolio</button>
        <button className={view === 'replay' ? 'active-buy' : ''} onClick={() => setView('replay')}>Replay a day</button>
      </div>
      {view === 'portfolio' ? <Portfolio /> : <Replay />}
    </div>
  );
}

function Portfolio() {
  const [state, setState] = useState(() => loadPaper());
  const [, force] = useState(0);

  // Re-mark positions periodically so P&L updates.
  useEffect(() => {
    const t = setInterval(() => force((n) => n + 1), 8000);
    return () => clearInterval(t);
  }, []);

  const marks = useMemo(
    () => state.positions.map((p) => ({
      pos: p,
      m: markPosition(p, { minutesLeft: minutesLeftFor(p) }),
    })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state.positions, state]
  );

  const openValue = marks.reduce((a, x) => a + x.m.value, 0);
  const unrealized = marks.reduce((a, x) => a + x.m.unrealizedPnl, 0);
  const total = state.cash + openValue;
  const totalReturn = (total - state.startingCash) / state.startingCash;
  const stats = summarize(state);

  const doSell = (id, price) => {
    const res = sellToClose(state, id, price);
    if (res.ok) setState(res.state);
  };
  const doReset = () => {
    if (window.confirm('Reset your paper portfolio to $10,000 and clear all trades?')) {
      setState(resetPaper());
    }
  };

  return (
    <>
      <div className="rh-card">
        <div className="rh-label">Paper portfolio value</div>
        <div className="rh-hero-value">{fmt$(total)}</div>
        <div className={`rh-change ${totalReturn >= 0 ? 'up' : 'down'}`}>
          <span className="arrow">{totalReturn >= 0 ? '▲' : '▼'}</span>
          {fmt$(Math.abs(total - state.startingCash))} ({pctSigned(totalReturn)}) all time
        </div>
      </div>

      <div className="rh-stats">
        <div className="rh-stat"><div className="k">Buying power</div><div className="v">{fmt$(state.cash)}</div></div>
        <div className="rh-stat"><div className="k">Open value</div><div className="v">{fmt$(openValue)}</div></div>
        <div className="rh-stat"><div className="k">Unrealized</div><div className="v" style={{ color: unrealized >= 0 ? 'var(--up)' : 'var(--down)' }}>{fmt$(unrealized)}</div></div>
        <div className="rh-stat"><div className="k">Realized</div><div className="v" style={{ color: stats.realizedPnl >= 0 ? 'var(--up)' : 'var(--down)' }}>{fmt$(stats.realizedPnl)}</div></div>
      </div>

      <h3>Open positions</h3>
      {!marks.length && <div className="rh-empty">No open positions. Buy a 0DTE contract from the Invest tab.</div>}
      {marks.map(({ pos, m }) => (
        <div key={pos.id} className="rh-row" style={{ cursor: 'default' }}>
          <div className="rh-col">
            <span className="rh-sym">{pos.underlying} ${pos.strike} <span className={`badge ${pos.optionType}`}>{pos.optionType.toUpperCase()}</span></span>
            <span className="rh-name">{pos.contracts}x @ {fmt$(pos.entryPrice)} · now {fmt$(m.markPrice)}</span>
          </div>
          <div className="rh-quote">
            <div className="rh-price" style={{ color: m.unrealizedPnl >= 0 ? 'var(--up)' : 'var(--down)' }}>{fmt$(m.unrealizedPnl)}</div>
            <div className={`rh-pct ${m.unrealizedPnl >= 0 ? 'up-fg' : 'down-fg'}`}>{pctSigned(m.unrealizedPct)}</div>
          </div>
          <button className="rh-btn danger sm" style={{ marginLeft: 8 }} onClick={() => doSell(pos.id, m.markPrice)}>Sell</button>
        </div>
      ))}

      <h3>Trade history</h3>
      {!state.history.length && <div className="rh-empty">No closed trades yet.</div>}
      {state.history.slice(0, 30).map((t) => (
        <div key={t.id} className="rh-row" style={{ cursor: 'default' }}>
          <div className="rh-col">
            <span className="rh-sym">{t.underlying} ${t.strike} {t.optionType.toUpperCase()}</span>
            <span className="rh-name">{t.contracts}x · {fmt$(t.entryPrice)} → {fmt$(t.exitPrice)}</span>
          </div>
          <div className="rh-quote">
            <div className="rh-price" style={{ color: t.realizedPnl >= 0 ? 'var(--up)' : 'var(--down)' }}>{fmt$(t.realizedPnl)}</div>
            <div className={`rh-pct ${t.realizedPnl >= 0 ? 'up-fg' : 'down-fg'}`}>{pctSigned(t.returnPct)}</div>
          </div>
        </div>
      ))}

      {state.history.length > 0 && (
        <div className="rh-stats" style={{ marginTop: 14 }}>
          <div className="rh-stat"><div className="k">Trades</div><div className="v">{stats.trades}</div></div>
          <div className="rh-stat"><div className="k">Win rate</div><div className="v">{(stats.winRate * 100).toFixed(0)}%</div></div>
          <div className="rh-stat"><div className="k">Profit factor</div><div className="v">{stats.profitFactor == null ? '∞' : stats.profitFactor.toFixed(2)}</div></div>
          <div className="rh-stat"><div className="k">Avg win / loss</div><div className="v">{fmt$(stats.avgWin)} / {fmt$(stats.avgLoss)}</div></div>
        </div>
      )}

      <button className="rh-btn secondary block" style={{ marginTop: 16 }} onClick={doReset}>Reset paper account (${STARTING_CASH.toLocaleString()})</button>
    </>
  );
}

const DEFAULT_DATE = (() => {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() - 1);
  return d.toISOString().slice(0, 10);
})();

function Replay() {
  const [ticker, setTicker] = useState('SPY');
  const [date, setDate] = useState(DEFAULT_DATE);
  const [bars, setBars] = useState(null);
  const [note, setNote] = useState(null);
  const [loading, setLoading] = useState(false);
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(4);
  const timer = useRef(null);

  // In-memory replay portfolio (not persisted).
  const [session, setSession] = useState(() => ({ cash: 10000, startingCash: 10000, positions: [], history: [] }));

  const load = () => {
    setLoading(true);
    setNote(null);
    setPlaying(false);
    fetchReplayDay(ticker, date)
      .then((d) => {
        setBars(d.bars || []);
        setIdx(0);
        setSession({ cash: 10000, startingCash: 10000, positions: [], history: [] });
        if (!d.bars?.length) setNote(d.notes?.[0] || 'No intraday data for that date.');
      })
      .catch((e) => setNote(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (!playing || !bars?.length) return undefined;
    timer.current = setInterval(() => {
      setIdx((i) => {
        if (i >= bars.length - 1) { setPlaying(false); return i; }
        return i + 1;
      });
    }, Math.max(1200 / speed, 80));
    return () => clearInterval(timer.current);
  }, [playing, speed, bars]);

  const total = bars?.length || 0;
  const curBar = bars && total ? bars[Math.min(idx, total - 1)] : null;
  const spot = curBar ? Number(curBar.c) : null;

  // Assume the replayed day is the 0DTE expiry; minutes left = bars remaining
  // scaled by the bar interval (approx, good enough for practice).
  const minutesLeft = curBar ? Math.max((total - idx) * 5, 1) : 1;
  const clock = curBar ? new Date(curBar.t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '--:--';

  const scan = useMemo(() => {
    if (spot == null) return null;
    const chain = buildSyntheticChain(ticker, spot, minutesLeft, { seed: idx + 1, expiration: date });
    return scanChains([chain], { accountSize: 10000, riskPct: 0.02, maxResults: 8 });
  }, [ticker, spot, minutesLeft, idx, date]);

  const results = scan?.results || [];

  // Mark session positions at current synthetic spot.
  const marks = (session.positions || []).map((p) => ({
    pos: p, m: markPosition(p, { spot, minutesLeft }),
  }));
  const openValue = marks.reduce((a, x) => a + x.m.value, 0);
  const totalVal = session.cash + openValue;

  const buy = (o) => {
    const res = buyToOpen(session, o, 1, { price: o.ask });
    if (res.ok) setSession(res.state);
  };
  const sell = (id, price) => {
    const res = sellToClose(session, id, price);
    if (res.ok) setSession(res.state);
  };

  return (
    <>
      <div className="rh-card">
        <div className="rh-inline">
          <div style={{ flex: 1 }}>
            <span className="rh-label">Ticker</span>
            <input className="rh-input" value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())} />
          </div>
          <div style={{ flex: 1 }}>
            <span className="rh-label">Date (last ~30d)</span>
            <input className="rh-input" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </div>
        </div>
        <button className="rh-btn block" style={{ marginTop: 12 }} onClick={load} disabled={loading}>
          {loading ? 'Loading…' : 'Load day'}
        </button>
        {note && <div className="rh-lead" style={{ marginTop: 8 }}>{note}</div>}
        <p className="rh-lead" style={{ marginTop: 8 }}>
          Real underlying prices, <strong>synthetic</strong> option chains (historical option quotes aren't free). Practice only.
        </p>
      </div>

      {curBar && (
        <>
          <div className="rh-card">
            <div className="rh-inline" style={{ justifyContent: 'space-between' }}>
              <span className="rh-replay-clock">🕒 {clock}</span>
              <span className="rh-hero-value" style={{ fontSize: 24 }}>{fmt$(spot)}</span>
            </div>
            <div className="rh-progressbar"><span style={{ width: `${(idx / Math.max(total - 1, 1)) * 100}%` }} /></div>
            <div className="rh-inline" style={{ marginTop: 10 }}>
              <button className="rh-btn sm" onClick={() => setPlaying((p) => !p)}>{playing ? '⏸ Pause' : '▶ Play'}</button>
              <button className="rh-btn secondary sm" onClick={() => setIdx((i) => Math.min(i + 1, total - 1))}>Step ▸</button>
              <select className="rh-input" style={{ maxWidth: 90 }} value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
                <option value={1}>1×</option>
                <option value={4}>4×</option>
                <option value={10}>10×</option>
                <option value={30}>30×</option>
              </select>
            </div>
          </div>

          <div className="rh-stats">
            <div className="rh-stat"><div className="k">Session value</div><div className="v">{fmt$(totalVal)}</div></div>
            <div className="rh-stat"><div className="k">P&L</div><div className="v" style={{ color: totalVal >= session.startingCash ? 'var(--up)' : 'var(--down)' }}>{fmt$(totalVal - session.startingCash)}</div></div>
          </div>

          <h3>Opportunities @ {clock}</h3>
          {!results.length && <div className="rh-empty">No qualifying contracts at this moment.</div>}
          {results.map((r) => {
            const o = r.opportunity;
            return (
              <div key={o.symbol} className="rh-row" style={{ cursor: 'default' }}>
                <div className="rh-col">
                  <span className="rh-sym">${o.strike} <span className={`badge ${o.option_type}`}>{o.option_type.toUpperCase()}</span></span>
                  <span className="rh-name">edge {(o.edge_pct * 100).toFixed(0)}% · {o.minutes_to_expiry}m</span>
                </div>
                <div className="rh-quote"><div className="rh-price">{fmt$(o.ask)}</div></div>
                <button className="rh-btn sm" style={{ marginLeft: 8 }} onClick={() => buy(o)}>Buy 1</button>
              </div>
            );
          })}

          <h3>Session positions</h3>
          {!marks.length && <div className="rh-empty">No positions yet.</div>}
          {marks.map(({ pos, m }) => (
            <div key={pos.id} className="rh-row" style={{ cursor: 'default' }}>
              <div className="rh-col">
                <span className="rh-sym">${pos.strike} {pos.optionType.toUpperCase()}</span>
                <span className="rh-name">{pos.contracts}x @ {fmt$(pos.entryPrice)} · now {fmt$(m.markPrice)}</span>
              </div>
              <div className="rh-quote">
                <div className="rh-price" style={{ color: m.unrealizedPnl >= 0 ? 'var(--up)' : 'var(--down)' }}>{fmt$(m.unrealizedPnl)}</div>
              </div>
              <button className="rh-btn danger sm" style={{ marginLeft: 8 }} onClick={() => sell(pos.id, m.markPrice)}>Sell</button>
            </div>
          ))}
        </>
      )}
    </>
  );
}
