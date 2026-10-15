import type { TermGpaPoint } from '../types/studentIntelligenceProfile';

export const MIN_TREND_TERMS: number;
export function shortTermLabel(termKey: string): string;
export function gpaDomain(values: Array<number | null>): { min: number; max: number };

export interface PlacedGpaPoint extends TermGpaPoint {
  x: number;
  termY: number;
  cumulativeY: number | null;
  axisLabel: string | null;
}

export function gpaTrendLayout(
  points: TermGpaPoint[],
  options: { width: number; height: number; padLeft?: number; padRight?: number; padTop?: number; padBottom?: number },
): {
  domain: { min: number; max: number };
  ticks: Array<{ value: number; y: number }>;
  points: PlacedGpaPoint[];
  solidCount: number;
  baselineY: number;
  plotLeft: number;
  plotRight: number;
};

export function polylinePoints(placed: PlacedGpaPoint[], key: 'termY' | 'cumulativeY'): string;

export function sparklinePoints(
  points: TermGpaPoint[],
  options: { width: number; height: number; pad?: number },
): { solid: string; projected: string; last: { x: number; y: number } | null };
