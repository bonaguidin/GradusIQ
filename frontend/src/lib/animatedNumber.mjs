// Pure math for AnimatedNumber.tsx: how a figure travels from its old value to
// its new one, and how the change is written. No React, no DOM --
// animatedNumber.test.mjs pins it.

export function easeOutCubic(t) {
  const clamped = Math.min(1, Math.max(0, t));
  return 1 - (1 - clamped) ** 3;
}

export function interpolate(from, to, progress) {
  return from + (to - from) * easeOutCubic(progress);
}

// How many decimals a value prints with as-is (81.4 -> 1, 85 -> 0), so a
// figure the app used to show raw keeps exactly the same text.
export function decimalsOf(value) {
  if (!Number.isFinite(value)) return 0;
  const text = String(value);
  const dot = text.indexOf('.');
  return dot < 0 || text.includes('e') ? 0 : text.length - dot - 1;
}

// "+0.11" / "−0.11" at the figure's own precision, or null when the change
// rounds away to nothing at that precision. Uses a true minus sign.
export function formatDelta(delta, decimals) {
  if (!Number.isFinite(delta)) return null;
  const rounded = Number(delta.toFixed(decimals));
  if (rounded === 0) return null;
  return `${rounded > 0 ? '+' : '−'}${Math.abs(rounded).toFixed(decimals)}`;
}
