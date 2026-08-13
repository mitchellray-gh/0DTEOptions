// Zero-dependency SVG sparkline. Draws a tiny line coloured by net direction.
import React, { useMemo } from 'react';

export default function Sparkline({ points, width = 80, height = 34, up }) {
  const path = useMemo(() => {
    const vals = (points || []).filter((v) => Number.isFinite(v));
    if (vals.length < 2) return null;
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const span = max - min || 1;
    const stepX = width / (vals.length - 1);
    return vals
      .map((v, i) => {
        const x = i * stepX;
        const y = height - ((v - min) / span) * (height - 4) - 2;
        return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ');
  }, [points, width, height]);

  const rising = up ?? (() => {
    const vals = (points || []).filter((v) => Number.isFinite(v));
    return vals.length >= 2 ? vals[vals.length - 1] >= vals[0] : true;
  })();
  const color = rising ? 'var(--up)' : 'var(--down)';

  if (!path) return <svg width={width} height={height} className="rh-spark" />;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="rh-spark" preserveAspectRatio="none">
      <path d={path} fill="none" stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
