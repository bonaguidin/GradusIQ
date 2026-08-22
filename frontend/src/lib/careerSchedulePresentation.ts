import type {
  CareerOptimizedScheduleResponse,
  CareerOptimizationStatus,
  RequirementCandidateRanking,
} from '../api/careerOptimizedSchedule.ts';
import type { ScheduleResult } from '../api/degreeSchedule.ts';
import { displayTermKey } from './degreeSchedulePresentation.ts';

export interface CoursePlacement {
  courseCode: string;
  termKey: string;
}

export interface CareerScheduleChange {
  requirementGroupId: string;
  academicCourses: CoursePlacement[];
  optimizedCourses: CoursePlacement[];
  addedCourseCodes: string[];
  removedCourseCodes: string[];
  movedCourseCodes: string[];
  unchangedCourseCodes: string[];
  careerRanked: boolean;
  candidateId: string | null;
  rankingReason: string | null;
  skillAlignmentExplanation: string | null;
}

export interface CourseTermMove {
  courseCode: string;
  fromTermKey: string;
  toTermKey: string;
}

export interface CareerScheduleComparison {
  changes: CareerScheduleChange[];
  changedChoiceCount: number;
  hasChanges: boolean;
}

export interface CareerOptimizationCopy {
  heading: string;
  message: string;
  tone: 'success' | 'warning' | 'neutral';
}

function byRequirement(schedule: ScheduleResult): Map<string, CoursePlacement[]> {
  const result = new Map<string, CoursePlacement[]>();
  for (const term of schedule.terms) {
    for (const course of term.courses) {
      const placements = result.get(course.requirement_group_id) ?? [];
      placements.push({ courseCode: course.course_code, termKey: term.term_key });
      result.set(course.requirement_group_id, placements);
    }
  }
  return result;
}

function sortedPlacements(placements: CoursePlacement[]): CoursePlacement[] {
  return [...placements].sort((left, right) =>
    left.courseCode.localeCompare(right.courseCode) || left.termKey.localeCompare(right.termKey));
}

function samePlacements(left: CoursePlacement[], right: CoursePlacement[]): boolean {
  const a = sortedPlacements(left);
  const b = sortedPlacements(right);
  return a.length === b.length
    && a.every((placement, index) => placement.courseCode === b[index].courseCode
      && placement.termKey === b[index].termKey);
}

function winningRanking(ranking: RequirementCandidateRanking | undefined) {
  return ranking?.ranked_candidates.find((candidate) => candidate.rank === 1) ?? null;
}

export function compareCareerSchedules(
  academic: ScheduleResult,
  optimized: ScheduleResult,
  rankings: RequirementCandidateRanking[],
): CareerScheduleComparison {
  const academicGroups = byRequirement(academic);
  const optimizedGroups = byRequirement(optimized);
  const rankingByGroup = new Map(rankings.map((ranking) => [ranking.requirement_group_id, ranking]));
  const groupIds = [...new Set([...academicGroups.keys(), ...optimizedGroups.keys()])];
  const changes = groupIds.flatMap((requirementGroupId) => {
    const academicCourses = sortedPlacements(academicGroups.get(requirementGroupId) ?? []);
    const optimizedCourses = sortedPlacements(optimizedGroups.get(requirementGroupId) ?? []);
    if (samePlacements(academicCourses, optimizedCourses)) return [];
    const academicCodes = new Set(academicCourses.map((course) => course.courseCode));
    const optimizedCodes = new Set(optimizedCourses.map((course) => course.courseCode));
    const winner = winningRanking(rankingByGroup.get(requirementGroupId));
    return [{
      requirementGroupId,
      academicCourses,
      optimizedCourses,
      addedCourseCodes: [...optimizedCodes].filter((code) => !academicCodes.has(code)).sort(),
      removedCourseCodes: [...academicCodes].filter((code) => !optimizedCodes.has(code)).sort(),
      movedCourseCodes: [...academicCodes].filter((code) => optimizedCodes.has(code)
        && academicCourses.find((course) => course.courseCode === code)?.termKey
          !== optimizedCourses.find((course) => course.courseCode === code)?.termKey).sort(),
      unchangedCourseCodes: [...academicCodes].filter((code) => optimizedCodes.has(code)
        && academicCourses.find((course) => course.courseCode === code)?.termKey
          === optimizedCourses.find((course) => course.courseCode === code)?.termKey).sort(),
      careerRanked: winner !== null,
      candidateId: winner?.candidate_id ?? null,
      rankingReason: winner?.ranking_reason ?? null,
      skillAlignmentExplanation: winner?.skill_alignment_explanation ?? null,
    } satisfies CareerScheduleChange];
  });
  return { changes, changedChoiceCount: changes.length, hasChanges: changes.length > 0 };
}

export function careerOptimizationCopy(
  status: CareerOptimizationStatus,
  summary: string | null,
): CareerOptimizationCopy {
  if (status === 'OPTIMIZED') return {
    heading: 'Career optimized',
    message: 'Career intelligence influenced only academically equivalent degree choices.',
    tone: 'success',
  };
  if (status === 'PARTIAL') return {
    heading: 'Some degree choices were career-ranked',
    message: 'The remaining choices use your academic schedule.',
    tone: 'warning',
  };
  if (status === 'FALLBACK') return {
    heading: "Career optimization wasn't available right now",
    message: 'Your academic schedule is unchanged.',
    tone: 'warning',
  };
  return {
    heading: 'Career optimization not applied',
    message: summary || 'There was nothing meaningful to career-rank for this plan.',
    tone: 'neutral',
  };
}

export function careerChangeHeading(change: CareerScheduleChange): string {
  const removed = change.removedCourseCodes.join(' + ');
  const added = change.addedCourseCodes.join(' + ');
  if (removed && added) return `${removed} → ${added}`;
  if (added) return `Add ${added}`;
  if (removed) return `Remove ${removed}`;
  return `${change.movedCourseCodes.join(' + ')} rescheduled`;
}

export function courseTermMoves(change: CareerScheduleChange): CourseTermMove[] {
  return change.movedCourseCodes.flatMap((courseCode) => {
    const from = change.academicCourses.find((course) => course.courseCode === courseCode);
    const to = change.optimizedCourses.find((course) => course.courseCode === courseCode);
    return from && to ? [{ courseCode, fromTermKey: from.termKey, toTermKey: to.termKey }] : [];
  });
}

function finalTermKey(schedule: ScheduleResult): string | null {
  return schedule.terms.length > 0 ? schedule.terms[schedule.terms.length - 1].term_key : null;
}

export function graduationTimingImpact(academic: ScheduleResult, optimized: ScheduleResult): string {
  const academicFinal = finalTermKey(academic);
  const optimizedFinal = finalTermKey(optimized);
  if (academicFinal === optimizedFinal) return 'Graduation timing did not change.';
  if (!academicFinal || !optimizedFinal) return 'The available schedules do not support a graduation-timing comparison.';
  return `The final planned term changed from ${displayTermKey(academicFinal)} to ${displayTermKey(optimizedFinal)}.`;
}

export function careerChangeSummary(comparison: CareerScheduleComparison): string {
  if (!comparison.hasChanges) {
    return 'Your academic plan already matches the strongest career-aligned choices among the available degree options.';
  }
  return `${comparison.changedChoiceCount} degree choice${comparison.changedChoiceCount === 1 ? '' : 's'} changed for career alignment.`;
}

export type CareerOptimizationView = 'academic' | 'optimized';
export type CareerOptimizationRunState =
  | { phase: 'idle' }
  | { phase: 'loading' }
  | { phase: 'done'; result: CareerOptimizedScheduleResponse; view: CareerOptimizationView }
  | { phase: 'transport-error'; message: string };

export const INITIAL_CAREER_OPTIMIZATION_STATE: CareerOptimizationRunState = { phase: 'idle' };

export function completedCareerOptimizationState(
  result: CareerOptimizedScheduleResponse,
): CareerOptimizationRunState {
  return {
    phase: 'done',
    result,
    view: result.status === 'OPTIMIZED' || result.status === 'PARTIAL' ? 'optimized' : 'academic',
  };
}
