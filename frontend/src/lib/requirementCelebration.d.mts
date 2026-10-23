import type { RequirementGroupResult } from '../api/requirementSatisfaction.mjs';

export interface CelebratedRequirement {
  id: string;
  name: string;
}

export interface CelebrationPlan {
  fresh: CelebratedRequirement[];
  remember: string[];
}

export declare function celebrationStorageKey(studentId: string): string;
export declare function satisfiedLeafRequirements(groups: RequirementGroupResult[]): CelebratedRequirement[];
export declare function parseCelebrated(raw: string | null): string[] | null;
export declare function planCelebration(
  celebrated: string[] | null,
  satisfied: CelebratedRequirement[],
): CelebrationPlan;
export declare function celebrationMessage(
  fresh: CelebratedRequirement[],
  progress: { satisfied: number; total: number },
): string;
