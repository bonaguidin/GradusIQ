import type { SyllabusProfileSummary } from '../api/syllabusGradeProfiles';

export type GradeColorKey = 'a' | 'b' | 'c' | 'd' | 'f';

export interface GradeRingSegment {
  name: string;
  weightPercent: number;
  score: number | null;
  status: 'completed' | 'projected' | null;
  /** false = ungraded (track only); true = counted, even at score 0. */
  graded: boolean;
  /** true = course weight not accounted for by any component; hatched, never fillable. */
  isShortfall: boolean;
  fillFraction: number;
  startAngle: number;
  endAngle: number;
  midAngle: number;
  trackPath: string;
  fillPath: string | null;
}

export interface GradeCardSetupModel {
  kind: 'setup';
  courseLabel: string;
  term: string | null;
  ariaLabel: string;
}

export interface GradeCardCategorylessModel {
  kind: 'categoryless';
  courseLabel: string;
  term: string | null;
  letter: string | null;
  colorKey: GradeColorKey | null;
  percentText: string | null;
  centerPrimary: string;
  centerSecondary: string | null;
  /** one full-circle track; fill runs to the overall percentage (null if none). */
  trackPath: string;
  fillPath: string | null;
  ariaLabel: string;
}

export interface GradeCardRingModel {
  kind: 'ring';
  courseLabel: string;
  term: string | null;
  letter: string | null;
  colorKey: GradeColorKey | null;
  percentText: string | null;
  centerPrimary: string;
  centerSecondary: string | null;
  hasGrades: boolean;
  segments: GradeRingSegment[];
  /** sum of every segmented component's weight (categories + decomposed assessments). */
  totalSegmentWeight: number;
  weightSumOff: boolean;
  /** >0 when segment weights fall short of 100; rendered as a shortfall segment. */
  weightShortfallPercent: number | null;
  /** >0 when segment weights exceed 100; segments are scaled to fit the circle. */
  weightOveragePercent: number | null;
  ariaLabel: string;
}

export type GradeCardModel = GradeCardSetupModel | GradeCardCategorylessModel | GradeCardRingModel;

export function arcPath(
  cx: number,
  cy: number,
  r: number,
  startAngle: number,
  endAngle: number,
): string;

export function circlePath(cx: number, cy: number, r: number): string;

export function gradeColorKey(letter: string | null | undefined): GradeColorKey | null;

export function buildGradeCardModel(
  profile: SyllabusProfileSummary,
  opts?: { gapDeg?: number; radius?: number; startAngle?: number },
): GradeCardModel;

export function hoveredCenter(
  segment: GradeRingSegment | null | undefined,
): { primary: string; secondary: string } | null;
