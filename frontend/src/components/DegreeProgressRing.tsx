import type { CSSProperties } from 'react';
import { AnimatedNumber } from './AnimatedNumber';

const SIZE = 44;
const STROKE = 5;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/**
 * The stat row's 4th tile -- satisfied-vs-total requirement groups (leaf
 * nodes only, see requirementProgress.mjs). The percentage sits in the same
 * number slot as the other three tiles, with the ring beside it drawing in
 * as the figure counts up, and the "X of Y" detail line underneath.
 * `total === 0` (no program evaluated yet, or a program with no
 * requirements) renders the same dash the other tiles show for missing
 * data, rather than a 0%-full or empty ring that would read as "0
 * satisfied" instead of "not available."
 */
const BURST_RAYS = 12;

/**
 * `celebrate` adds the requirement-done burst (RequirementCelebration.tsx):
 * once the ring has drawn in, a gold ring and sparks fly off it and the tile
 * gives the confirm button's slam. Decorative only, so it is aria-hidden and
 * disappears under reduced motion; the message beside it carries the news.
 */
export function DegreeProgressRing({ satisfied, total, celebrate = false }: { satisfied: number; total: number; celebrate?: boolean }) {
  if (total === 0) {
    return (
      <div className="overview-stat overview-stat--ring">
        <span className="overview-stat-value">—</span>
        <span className="overview-stat-label">Degree Progress</span>
      </div>
    );
  }

  const pct = Math.round((satisfied / total) * 100);
  const offset = CIRCUMFERENCE * (1 - satisfied / total);

  return (
    <div className={`overview-stat overview-stat--ring${celebrate ? ' is-celebrating' : ''}`}>
      <span className="overview-stat-value">
        <AnimatedNumber value={pct} decimals={0} suffix="%" countIn />
      </span>
      <span className="overview-stat-label">Degree Progress</span>
      <span className="overview-stat-detail">{satisfied} of {total} requirement groups satisfied</span>
      <svg
        className="degree-progress-ring"
        width={SIZE}
        height={SIZE}
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        role="img"
        aria-label={`${String(satisfied)} of ${String(total)} requirement groups satisfied`}
      >
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          fill="none"
          strokeWidth={STROKE}
          className="degree-progress-ring-track"
        />
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          fill="none"
          strokeWidth={STROKE}
          strokeDasharray={CIRCUMFERENCE}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
          className="degree-progress-ring-fill"
          // The draw-in starts from an empty ring (index.css, ring-draw).
          style={{ '--ring-empty': `${String(CIRCUMFERENCE)}px` } as CSSProperties}
        />
      </svg>
      {celebrate && (
        <span className="req-burst" aria-hidden="true">
          <span className="req-burst-ring" />
          {Array.from({ length: BURST_RAYS }, (_, i) => (
            <span key={i} className="req-burst-spark" style={{ '--spark-angle': `${String((360 / BURST_RAYS) * i)}deg` } as CSSProperties} />
          ))}
        </span>
      )}
    </div>
  );
}
