import type {
  AcademicCourse,
  AcademicTerm,
  CanonicalCareer,
  CanonicalCompleteness,
  CanonicalProvenance,
  RepeatExclusion,
  StudentIntelligenceProfile,
  TermGpaPoint,
} from '../types/studentIntelligenceProfile';

export interface AuthenticatedDashboardViewModel {
  studentId: string;
  name: string | null;
  initials: string;
  institutionId: string | null;
  institutionName: string | null;
  classification: string | null;
  expectedGraduation: string | null;
  majorCurrent: string | null;
  majorIntended: string | null;
  officialGpa: number | null;
  projectedGpa: number | null;
  inProgressWithCurrentGradeCount: number;
  gpaByTerm: TermGpaPoint[];
  completedHours: number;
  inProgressHours: number;
  earnedHours: number;
  courses: AcademicCourse[];
  terms: AcademicTerm[];
  repeatExclusions: RepeatExclusion[];
  career: CanonicalCareer;
  completeness: CanonicalCompleteness;
  provenance: CanonicalProvenance;
}

export function buildDashboardViewModel(
  profile: StudentIntelligenceProfile,
): AuthenticatedDashboardViewModel {
  const name = profile.identity.name;
  const initials = (name ?? '')
    .split(' ')
    .filter(Boolean)
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();

  return {
    studentId: profile.identity.student_id,
    name,
    initials,
    institutionId: profile.institution.id,
    institutionName: profile.institution.name,
    classification: profile.identity.classification,
    expectedGraduation: profile.identity.expected_graduation,
    majorCurrent: profile.academics.summary.major_current,
    majorIntended: profile.academics.summary.major_intended,
    officialGpa: profile.academics.gpa.official,
    projectedGpa: profile.academics.gpa.projected,
    inProgressWithCurrentGradeCount: profile.academics.gpa.in_progress_with_current_grade_count,
    gpaByTerm: profile.academics.gpa.by_term ?? [],
    completedHours: profile.academics.summary.completed_hours,
    inProgressHours: profile.academics.summary.in_progress_hours,
    earnedHours: profile.academics.summary.earned_hours,
    courses: profile.academics.courses,
    terms: profile.academics.terms,
    repeatExclusions: profile.academics.repeat_exclusions,
    career: profile.career,
    completeness: profile.completeness,
    provenance: profile.provenance,
  };
}
