import { useEffect, useRef, useState } from 'react';
import type { TermGpaPoint } from '../types/studentIntelligenceProfile';
import { MIN_TREND_TERMS, gpaTrendLayout, polylinePoints, sparklinePoints } from '../lib/gpaTrend.mjs';
import { formatFixed } from '../lib/format.mjs';

// The SVG is laid out at its rendered width (measured), not scaled from a
// fixed viewBox, so axis text stays at its token size from phone to desktop.
const DEFAULT_WIDTH = 640;
const HEIGHT = 240;

function pointDescription(point: TermGpaPoint): string {
  const cumulative = point.cumulative_gpa !== null ? `, cumulative ${formatFixed(point.cumulative_gpa, 2)}` : '';
  const projected = point.projected ? ' (projected from current grades)' : '';
  return `${point.label}: term GPA ${formatFixed(point.term_gpa, 2)}${cumulative}, ${point.gpa_hours} GPA hours${projected}`;
}

/**
 * GPA by term on the GPA Calculator page: term GPA (accent) and running
 * cumulative GPA (muted), with the in-progress term dashed and hollow because
 * it is projected from current grades. Clicking a term opens it in the term
 * tabs below. Fewer than MIN_TREND_TERMS terms shows a one-line note instead.
 */
export function GpaTrendChart({ points, onSelectTerm }: { points: TermGpaPoint[]; onSelectTerm?: (termKey: string) => void }) {
  const [hovered, setHovered] = useState<number | null>(null);
  const plotRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(DEFAULT_WIDTH);

  useEffect(() => {
    const node = plotRef.current;
    if (!node || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(([entry]) => {
      const next = Math.round(entry.contentRect.width);
      if (next > 0) setWidth(next);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [points.length]);

  if (points.length < MIN_TREND_TERMS) {
    return (
      <p className="gpa-trend-note">
        Your GPA chart appears once you have {MIN_TREND_TERMS} terms of grades on record.
      </p>
    );
  }

  const layout = gpaTrendLayout(points, { width, height: HEIGHT });
  const solid = layout.points.slice(0, layout.solidCount);
  const dashed = layout.solidCount > 0 ? layout.points.slice(layout.solidCount - 1) : layout.points;
  const hasProjected = layout.solidCount < layout.points.length;
  const active = hovered !== null ? layout.points[hovered] : null;

  return (
    <section className="card gpa-trend" aria-label="GPA by term">
      <div className="gpa-trend-header">
        <h3 className="term-courses-heading">GPA by term</h3>
        <ul className="gpa-trend-legend">
          <li><span className="gpa-trend-key gpa-trend-key--term" aria-hidden="true" />Term GPA</li>
          <li><span className="gpa-trend-key gpa-trend-key--cumulative" aria-hidden="true" />Cumulative</li>
          {hasProjected && <li><span className="gpa-trend-key gpa-trend-key--projected" aria-hidden="true" />Projected (current grades)</li>}
        </ul>
      </div>
      <div className="gpa-trend-plot" ref={plotRef}>
        <svg viewBox={`0 0 ${width} ${HEIGHT}`} width={width} height={HEIGHT} className="gpa-trend-svg" role="group" aria-label={`Term and cumulative GPA for ${points.length} terms`}>
          {layout.ticks.map((tick) => (
            <g key={tick.value}>
              <line className="gpa-trend-grid" x1={layout.plotLeft} x2={layout.plotRight} y1={tick.y} y2={tick.y} />
              <text className="gpa-trend-tick" x={layout.plotLeft - 8} y={tick.y + 4} textAnchor="end">{tick.value.toFixed(1)}</text>
            </g>
          ))}
          <polyline className="gpa-trend-line gpa-trend-line--cumulative" points={polylinePoints(solid, 'cumulativeY')} />
          <polyline className="gpa-trend-line gpa-trend-line--term" points={polylinePoints(solid, 'termY')} />
          {hasProjected && (
            <>
              <polyline className="gpa-trend-line gpa-trend-line--cumulative gpa-trend-line--projected" points={polylinePoints(dashed, 'cumulativeY')} />
              <polyline className="gpa-trend-line gpa-trend-line--term gpa-trend-line--projected" points={polylinePoints(dashed, 'termY')} />
            </>
          )}
          {layout.points.map((point, index) => (
            <g
              key={point.term_id}
              className={`gpa-trend-point${point.projected ? ' gpa-trend-point--projected' : ''}${hovered === index ? ' gpa-trend-point--active' : ''}`}
              role={onSelectTerm ? 'button' : 'img'}
              tabIndex={0}
              aria-label={pointDescription(point)}
              onMouseEnter={() => setHovered(index)}
              onMouseLeave={() => setHovered(null)}
              onFocus={() => setHovered(index)}
              onBlur={() => setHovered(null)}
              onClick={() => onSelectTerm?.(point.term_key)}
              onKeyDown={(event) => {
                if (onSelectTerm && (event.key === 'Enter' || event.key === ' ')) {
                  event.preventDefault();
                  onSelectTerm(point.term_key);
                }
              }}
            >
              <rect className="gpa-trend-hit" x={point.x - 24} y={0} width={48} height={layout.baselineY} />
              <circle className="gpa-trend-dot" cx={point.x} cy={point.termY} r={5} />
              {point.axisLabel && (
                <text className="gpa-trend-axis" x={point.x} y={HEIGHT - 10} textAnchor="middle">{point.axisLabel}</text>
              )}
            </g>
          ))}
          {/* One direct label: the latest term's GPA. Everything else is on hover. */}
          {(() => {
            const last = layout.points[layout.points.length - 1];
            return (
              <text className="gpa-trend-value" x={last.x} y={last.termY - 12} textAnchor="middle">
                {formatFixed(last.term_gpa, 2)}
              </text>
            );
          })()}
        </svg>
        {active && (
          <div
            className={`gpa-trend-tooltip${active.x > width * 0.75 ? ' gpa-trend-tooltip--end' : active.x < width * 0.25 ? ' gpa-trend-tooltip--start' : ''}`}
            role="status"
            style={{ left: `${(active.x / width) * 100}%`, top: `${(active.termY / HEIGHT) * 100}%` }}
          >
            <strong>{active.label}</strong>
            <span>Term GPA <b>{formatFixed(active.term_gpa, 2)}</b></span>
            {active.cumulative_gpa !== null && <span>Cumulative <b>{formatFixed(active.cumulative_gpa, 2)}</b></span>}
            <span>{active.gpa_hours} GPA hours{active.projected ? ' · projected' : ''}</span>
          </div>
        )}
      </div>
    </section>
  );
}

/** Cumulative-GPA sparkline for the Overview GPA tile; links to the chart. */
export function GpaSparkline({ points, onOpen }: { points: TermGpaPoint[]; onOpen: () => void }) {
  if (points.length < MIN_TREND_TERMS) return null;
  const width = 96;
  const height = 28;
  const line = sparklinePoints(points, { width, height });
  if (!line.solid) return null;
  return (
    <button type="button" className="gpa-sparkline" onClick={onOpen} aria-label="See GPA by term">
      <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} aria-hidden="true">
        <polyline className="gpa-sparkline-line" points={line.solid} />
        {line.projected && <polyline className="gpa-sparkline-line gpa-sparkline-line--projected" points={line.projected} />}
        {line.last && <circle className="gpa-sparkline-dot" cx={line.last.x} cy={line.last.y} r={2.5} />}
      </svg>
      <span className="gpa-sparkline-link">GPA history →</span>
    </button>
  );
}
