export interface StudentIntelligenceProfile {
  contract_version: '1.0';
  identity: {
    student_id: string;
    name: string | null;
    classification: string | null;
    expected_graduation: string | null;
    onboarding_stage: number | null;
  };
  institution: {
    id: string | null;
    name: string | null;
    relationship: 'home' | null;
  };
  academics: {
    summary: {
      major_current: string | null;
      major_intended: string | null;
      confirmed_course_count: number;
      completed_hours: number;
      in_progress_hours: number;
      earned_hours: number;
    };
    terms: AcademicTerm[];
    courses: AcademicCourse[];
    gpa: {
      official: number | null;
      projected: number | null;
      computable: boolean;
      in_progress_with_current_grade_count: number;
      // Oldest first. Optional: the demo profile and older payloads omit it.
      by_term?: TermGpaPoint[];
      source: 'gpa_service';
    };
    repeat_exclusions: RepeatExclusion[];
  };
  career: CanonicalCareer;
  completeness: CanonicalCompleteness;
  provenance: CanonicalProvenance;
}

export interface AcademicTerm {
  id: string;
  institution_id: string;
  label: string;
  year: number;
  season: string;
  sequence: number;
}

export interface AcademicCourse {
  id: string;
  term_id: string | null;
  institution_id: string | null;
  course_code: string;
  title: string | null;
  credit_hours: number;
  letter_grade: string | null;
  credit_type: string;
  status: string;
  source: string;
}

export interface RepeatExclusion {
  excluded_course_id: string;
  superseded_by_course_id: string;
  reason: 'excluded_by_repeat';
}

export interface CanonicalCareerItem {
  source?: string | null;
  [key: string]: unknown;
}

export interface CanonicalCareer {
  confirmed: boolean;
  target_roles: string[];
  interests: string[];
  career_goals: string | null;
  geographic_preference: string | null;
  ai_anxiety_level: string | null;
  skills: {
    technical: string[];
    soft: string[];
    ai_exposure: string | null;
  };
  certifications: CanonicalCareerItem[];
  work_experience: CanonicalCareerItem[];
  projects: CanonicalCareerItem[];
}

export interface CanonicalCompleteness {
  career: {
    confirmed_profile: boolean;
    target_role_present: boolean;
    skills_present: boolean;
    certifications_present: boolean;
    work_experience_present: boolean;
    projects_present: boolean;
    ready_for_career_features: boolean;
  };
  academics: {
    transcript_data_present: boolean;
    terms_present: boolean;
    gpa_computable: boolean;
    ready_for_academic_features: boolean;
  };
  overall: 'minimal' | 'partial' | 'ready';
}

export interface CanonicalProvenance {
  career_profile: string | null;
  certifications: string[];
  work_experience: string[];
  projects: string[];
  academics: string[];
  credit_type_limitation: string | null;
}

export interface MeProfile {
  student: {
    id: string;
    name: string | null;
    institution: string | null;
  };
  career: unknown;
  intelligence_profile: StudentIntelligenceProfile;
}

export interface TermGpaPoint {
  term_id: string;
  term_key: string;
  label: string;
  term_gpa: number;
  cumulative_gpa: number | null;
  gpa_hours: number;
  projected: boolean;
}
