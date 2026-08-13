import React from 'react';
import { useOutletContext } from 'react-router-dom';
import { loadPaper, summarize } from '../lib/paper.js';
import { loadProgress } from '../lib/curriculum.js';
import { LESSONS } from '../lib/curriculum.js';
import { fmt$ } from '../lib/format.js';

export default function ProfilePage() {
  const { settings, setSettings, watchlist } = useOutletContext();
  const paper = loadPaper();
  const stats = summarize(paper);
  const progress = loadProgress();
  const lessonsDone = LESSONS.filter((l) => progress[l.id]?.done).length;

  const set = (patch) => setSettings({ ...settings, ...patch });

  return (
    <div className="rh-page">
      <div className="rh-card">
        <div className="rh-label">Educational account</div>
        <div className="rh-hero-value">Paper trader</div>
        <p className="rh-lead" style={{ marginTop: 6 }}>
          This app never connects to a brokerage and never places real orders. Everything is simulated for learning.
        </p>
      </div>

      <div className="rh-stats">
        <div className="rh-stat"><div className="k">Cash</div><div className="v">{fmt$(paper.cash)}</div></div>
        <div className="rh-stat"><div className="k">Closed trades</div><div className="v">{stats.trades}</div></div>
        <div className="rh-stat"><div className="k">Win rate</div><div className="v">{stats.trades ? `${(stats.winRate * 100).toFixed(0)}%` : '—'}</div></div>
        <div className="rh-stat"><div className="k">Lessons done</div><div className="v">{lessonsDone}/{LESSONS.length}</div></div>
      </div>

      <h3>Trade settings</h3>
      <div className="rh-card">
        <div style={{ marginBottom: 12 }}>
          <span className="rh-label">Account size ($) — used for position sizing</span>
          <input className="rh-input" type="number" min="100" step="100" value={settings.accountSize}
                 onChange={(e) => set({ accountSize: Number(e.target.value) })} />
        </div>
        <div style={{ marginBottom: 12 }}>
          <span className="rh-label">Risk per trade (%)</span>
          <input className="rh-input" type="number" min="0.1" max="100" step="0.1" value={settings.riskPct}
                 onChange={(e) => set({ riskPct: Number(e.target.value) })} />
        </div>
        <div style={{ marginBottom: 12 }}>
          <span className="rh-label">Minimum edge (%)</span>
          <input className="rh-input" type="number" min="0" step="0.5" value={settings.minEdge}
                 onChange={(e) => set({ minEdge: Number(e.target.value) })} />
        </div>
        <div>
          <span className="rh-label">Contract type filter</span>
          <select className="rh-input" value={settings.type} onChange={(e) => set({ type: e.target.value })}>
            <option value="all">All</option>
            <option value="call">Calls only</option>
            <option value="put">Puts only</option>
          </select>
        </div>
      </div>

      <h3>Tracking</h3>
      <div className="rh-card">
        <p className="rh-lead" style={{ margin: 0 }}>{watchlist.length} symbols on your watchlist: {watchlist.join(', ')}</p>
      </div>

      <div className="rh-card" style={{ background: 'rgba(255,179,64,0.08)', borderColor: 'rgba(255,179,64,0.3)' }}>
        <h4 style={{ color: '#ffb340' }}>Risk disclaimer</h4>
        <p style={{ color: '#ffb340' }}>
          0DTE options are extremely high-risk and can lose 100% of premium in minutes. Fair-value
          estimates use Black-Scholes with a volume-weighted reference IV from the same chain — an
          approximation, not a guarantee. Quotes are delayed. This tool is for education only and does
          not provide financial advice or route real trades.
        </p>
      </div>
    </div>
  );
}
