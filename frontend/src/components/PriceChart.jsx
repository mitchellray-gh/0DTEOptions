// Robinhood-style area price chart (zero-dependency SVG). Green when the period
// closed up, red when down. Includes a soft gradient fill and a baseline.
import React, { useMemo } from 'react';

export default function PriceChart({ bars, height = 200, prevClose = null }) {
  const closes = useMemo(
    () => (bars || []).map((b) => Number(b.c)).filter((v) => Number.isFinite(v)),
    [bars]
  );

  const geom = useMemo(() => {
    if (closes.length < 2) return null;
    const width = 1000; // viewBox units; scales to container
    const min = Math.min(...closes, prevClose ?? Infinity);
    const max = Math.max(...closes, prevClose ?? -Infinity);
    const span = max - min || 1;
    const pad = 8;
    const h = height;
    const stepX = width / (closes.length - 1);
    const y = (v) => h - pad - ((v - min) / span) * (h - pad * 2);
    const line = closes.map((v, i) => `${i === 0 ? 'M' : 'L'}${(i * stepX).toFixed(2)},${y(v).toFixed(2)}`).join(' ');
    const area = `${line} L${width},${h} L0,${h} Z`;
    const baseY = prevClose != null ? y(prevClose) : null;
    return { width, h, line, area, baseY };
  }, [closes, height, prevClose]);

  if (!geom) return <div className="rh-empty">No chart data.</div>;

  const first = closes[0];
  const last = closes[closes.length - 1];
  const up = last >= (prevClose ?? first);
  const color = up ? 'var(--up)' : 'var(--down)';
  const gid = up ? 'grad-up' : 'grad-down';

  return (
    <div className="rh-chart-wrap">
      <svg
        className="rh-chart"
        viewBox={`0 0 ${geom.width} ${geom.h}`}
        height={height}
        preserveAspectRatio="none"
        role="img"
        aria-label="price chart"
      >
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.28" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {geom.baseY != null && (
          <line
            x1="0" y1={geom.baseY} x2={geom.width} y2={geom.baseY}
            stroke="var(--muted)" strokeWidth="1" strokeDasharray="4 5" opacity="0.5"
          />
        )}
        <path d={geom.area} fill={`url(#${gid})`} />
        <path d={geom.line} fill="none" stroke={color} strokeWidth="2.4" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      </svg>
    </div>
  );
}
