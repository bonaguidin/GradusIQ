import { useEffect, useRef } from 'react';
import { decimalsOf, formatDelta, interpolate } from '../lib/animatedNumber.mjs';
import { formatFixed } from '../lib/format.mjs';

// --t-data in interaction.css; interactionLayer.test.mjs keeps the two in step.
const COUNT_MS = 600;

interface AnimatedNumberProps {
  value: number | null | undefined;
  /** Fixed decimals, e.g. 2 for a GPA. Defaults to however many the value prints with. */
  decimals?: number;
  suffix?: string;
  fallback?: string;
  /** After a change, show how far the figure moved beside it. */
  showDelta?: boolean;
  /**
   * Also count up from zero when the figure first appears. Only for a page's
   * headline figures (Overview's stat tiles), never for numbers in a list.
   */
  countIn?: boolean;
}

/**
 * A figure that counts to its new value when it changes -- never on first
 * render, so a page load doesn't set every number on screen rolling. The one
 * exception is countIn, which a page opts into for its few headline figures.
 *
 * The element's real text is always the final value. The counting digits are
 * drawn over it from data-count (.figure-count in interaction.css), so tests,
 * copy-paste and screen readers read the true figure at every moment rather
 * than a frame of the animation.
 */
export function AnimatedNumber({ value, decimals, suffix = '', fallback = '—', showDelta = false, countIn = false }: AnimatedNumberProps) {
  const target = typeof value === 'number' && Number.isFinite(value) ? value : null;
  const places = decimals ?? (target === null ? 0 : decimalsOf(target));
  const ref = useRef<HTMLSpanElement>(null);
  const settled = useRef(target); // the value the next change is measured from
  const drawn = useRef(target); // what is on screen, mid-count or not
  // Still owed its count from zero. Cleared once that count finishes rather
  // than when it starts, so an effect that re-runs before the first frame
  // (React's development double-run) starts it again instead of losing it.
  const pendingCountIn = useRef(countIn);

  useEffect(() => {
    const el = ref.current;
    const prior = settled.current;
    settled.current = target;
    if (!el) return undefined;

    const countingIn = pendingCountIn.current && target !== null;
    if (countingIn) drawn.current = 0;

    // First value arriving, a value going away, or no change: nothing to count.
    if (!countingIn && (target === null || prior === null || drawn.current === null || prior === target)) {
      drawn.current = target;
      el.removeAttribute('data-count');
      if (target === null) {
        el.removeAttribute('data-delta');
        el.removeAttribute('data-delta-sign');
      }
      return undefined;
    }

    if (showDelta && !countingIn && prior !== null) {
      const delta = formatDelta(target - prior, places);
      el.removeAttribute('data-delta');
      el.removeAttribute('data-delta-sign');
      if (delta) {
        void el.offsetWidth; // replay the chip's entrance on every change
        el.setAttribute('data-delta', delta);
        el.setAttribute('data-delta-sign', target > prior ? 'up' : 'down');
      }
    }

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      pendingCountIn.current = false;
      drawn.current = target;
      el.removeAttribute('data-count');
      return undefined;
    }

    const from = drawn.current ?? 0;
    const start = performance.now();
    let frame = 0;
    const step = (now: number) => {
      const progress = Math.min(1, (now - start) / COUNT_MS);
      drawn.current = interpolate(from, target, progress);
      if (progress < 1) {
        el.setAttribute('data-count', `${formatFixed(drawn.current, places)}${suffix}`);
        frame = requestAnimationFrame(step);
      } else {
        pendingCountIn.current = false;
        el.removeAttribute('data-count');
      }
    };
    el.setAttribute('data-count', `${formatFixed(from, places)}${suffix}`);
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target, places, suffix, showDelta]);

  return (
    <span ref={ref} className="figure-count">
      {target === null ? fallback : `${formatFixed(target, places)}${suffix}`}
    </span>
  );
}
