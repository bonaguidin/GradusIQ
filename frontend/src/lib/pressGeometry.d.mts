export interface PressRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface PressPoint {
  x: number;
  y: number;
}

export interface PressGeometry {
  /** Origin, in px from the control's left edge. */
  x: number;
  /** Origin, in px from the control's top edge. */
  y: number;
  /** Distance from the origin to the farthest corner, in px. */
  reach: number;
}

export function pressGeometry(rect: PressRect, point: PressPoint | null): PressGeometry;
