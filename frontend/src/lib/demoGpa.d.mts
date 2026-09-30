export const ASSUMED_COMPLETED_HOURS: Record<'freshman' | 'sophomore' | 'junior' | 'senior', number>;

export function demoCompletedHours(classification: string | null, recordedCompletedHours?: number): number;

export interface DemoGpaCourse {
  status: string;
  credit_hours: number | string;
  letter_grade: string | null;
  credit_type?: string;
}

export interface DemoGradeRow {
  letter: string;
  points: number | null;
  counts_toward_gpa: boolean;
}

export interface DemoGpaSummary {
  projectedGpa: number | null;
  earnedHours: number;
  inProgressWithCurrentGradeCount: number;
}

export function demoGpaSummary(input: {
  officialGpa: number | null;
  classification: string | null;
  courses: DemoGpaCourse[];
  grades: DemoGradeRow[];
}): DemoGpaSummary;
