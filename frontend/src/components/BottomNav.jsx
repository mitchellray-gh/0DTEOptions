// Robinhood-style bottom tab bar.
import React from 'react';
import { NavLink } from 'react-router-dom';

const TABS = [
  { to: '/', label: 'Invest', ico: '📈', end: true },
  { to: '/practice', label: 'Practice', ico: '🎯' },
  { to: '/learn', label: 'Learn', ico: '🎓' },
  { to: '/discover', label: 'Discover', ico: '🔍' },
  { to: '/profile', label: 'Profile', ico: '👤' },
];

export default function BottomNav() {
  return (
    <nav className="rh-bottomnav">
      {TABS.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          end={t.end}
          className={({ isActive }) => `rh-navitem${isActive ? ' active' : ''}`}
        >
          <span className="ico" aria-hidden>{t.ico}</span>
          {t.label}
        </NavLink>
      ))}
    </nav>
  );
}
