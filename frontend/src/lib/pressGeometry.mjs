// Where a press effect starts on a control and how far it must travel to cover
// it. Pure -- interaction.ts reads the rect and pointer, interaction.css draws
// the circle, and pressGeometry.test.mjs pins the math.
//
// `reach` is the distance from the origin to the control's farthest corner, so
// a circle of that radius centred on the origin covers the whole control no
// matter where the pointer came in. A null point means keyboard or
// programmatic activation, which has no position: the effect starts centred.

function clamp(n, lo, hi) {
  return Math.max(lo, Math.min(hi, n));
}

export function pressGeometry(rect, point) {
  const width = Math.max(0, rect.width);
  const height = Math.max(0, rect.height);
  // Leave events report a coordinate a pixel or so outside the control.
  const x = point ? clamp(point.x - rect.left, 0, width) : width / 2;
  const y = point ? clamp(point.y - rect.top, 0, height) : height / 2;
  const reach = Math.hypot(Math.max(x, width - x), Math.max(y, height - y));
  return { x, y, reach };
}
