import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, MemoryRouter } from 'react-router-dom';
import type { Session } from '@supabase/supabase-js';
import { AuthContext, type AuthContextValue } from './auth/AuthContext';
import { StudentAccountProblem } from './auth/AccountStateScreens';
import { AuthenticatedDashboard } from './pages/AuthenticatedDashboard';
import { ProfileCompletionPage } from './pages/ProfileCompletionPage';
import { applyInstitutionTheme, fetchInstitutionThemeByName } from './lib/institutionTheme';
import type { StudentIntelligenceProfile } from './types/studentIntelligenceProfile';
import './index.css';
import './interaction.ts';

const mode = new URLSearchParams(location.search).get('mode') ?? 'complete';
const institution = new URLSearchParams(location.search).get('institution') === 'smu'
  ? 'Southern Methodist University'
  : 'Texas A&M University';

const base: StudentIntelligenceProfile = {
  contract_version: '1.0',
  identity: { student_id: 'student-real', name: 'Alex Morgan', classification: 'Sophomore', expected_graduation: 'Spring 2028', onboarding_stage: 3 },
  institution: { id: 'institution-real', name: institution, relationship: 'home' },
  academics: {
    summary: { major_current: 'Computer Science', major_intended: 'N/A', confirmed_course_count: 1, completed_hours: 3, in_progress_hours: 0, earned_hours: 3 },
    terms: [{ id: 'term-1', institution_id: 'institution-real', label: 'Fall 2025', year: 2025, season: 'fall', sequence: 1 }],
    courses: [{ id: 'course-1', term_id: 'term-1', institution_id: 'institution-real', course_code: 'CS 101', title: 'Introduction to Computing', credit_hours: 3, letter_grade: 'A', credit_type: 'resident', status: 'completed', source: 'transcript_parse' }],
    gpa: { official: 4, projected: 4, computable: true, in_progress_with_current_grade_count: 0, source: 'gpa_service' },
    repeat_exclusions: [],
  },
  career: {
    confirmed: true, target_roles: ['Software Engineer'], interests: ['systems'], career_goals: 'Build reliable software', geographic_preference: null, ai_anxiety_level: null,
    skills: { technical: ['TypeScript'], soft: ['Communication'], ai_exposure: 'Coursework' },
    certifications: [{ name: 'Cloud Fundamentals', issuer: 'Example', source: 'resume_parse' }],
    work_experience: [{ employer: 'Acme', role: 'Intern', source: 'resume_parse' }],
    projects: [{ name: 'Planner', description: 'A planning app', source: 'manual' }],
  },
  completeness: {
    career: { confirmed_profile: true, target_role_present: true, skills_present: true, certifications_present: true, work_experience_present: true, projects_present: true, ready_for_career_features: true },
    academics: { transcript_data_present: true, terms_present: true, gpa_computable: true, ready_for_academic_features: true },
    overall: 'ready',
  },
  provenance: { career_profile: 'resume_parse', certifications: ['resume_parse'], work_experience: ['resume_parse'], projects: ['manual'], academics: ['transcript_parse'], credit_type_limitation: 'Transcript credit classification limitation.' },
};

const profile = structuredClone(base);
if (mode === 'career' || mode === 'minimal') {
  profile.academics.courses = [];
  profile.academics.terms = [];
  profile.academics.gpa = { official: null, projected: null, computable: false, in_progress_with_current_grade_count: 0, source: 'gpa_service' };
  profile.academics.summary.confirmed_course_count = 0;
  profile.completeness.academics = { transcript_data_present: false, terms_present: false, gpa_computable: false, ready_for_academic_features: false };
}
if (mode === 'academic' || mode === 'minimal') {
  profile.career = { confirmed: false, target_roles: [], interests: [], career_goals: null, geographic_preference: null, ai_anxiety_level: null, skills: { technical: [], soft: [], ai_exposure: null }, certifications: [], work_experience: [], projects: [] };
  profile.completeness.career = { confirmed_profile: false, target_role_present: false, skills_present: false, certifications_present: false, work_experience_present: false, projects_present: false, ready_for_career_features: false };
}
if (mode !== 'complete') profile.completeness.overall = mode === 'minimal' ? 'minimal' : 'partial';

// Additive and opt-in via ?currentTerm=inprogress, same pattern as ?career=
// below -- every mode above still renders exactly as it did without this
// param. Adds a second, in-progress term/course on top of whatever `mode`
// already set up, for Overview's current-term card.
if (new URLSearchParams(location.search).get('currentTerm') === 'inprogress') {
  profile.academics.terms.push({ id: 'term-2', institution_id: 'institution-real', label: 'Fall 2026', year: 2026, season: 'fall', sequence: 2 });
  profile.academics.courses.push(
    { id: 'course-2', term_id: 'term-2', institution_id: 'institution-real', course_code: 'CS 221', title: 'Data Structures and Algorithms', credit_hours: 4, letter_grade: null, credit_type: 'resident', status: 'in_progress', source: 'transcript_parse' },
    { id: 'course-3', term_id: 'term-2', institution_id: 'institution-real', course_code: 'MATH 251', title: 'Engineering Mathematics III', credit_hours: 3, letter_grade: null, credit_type: 'resident', status: 'in_progress', source: 'transcript_parse' },
  );
}

// ── Career fixtures for the Phase 3 redesign ──────────────────────────────
// Additive and opt-in via ?career=, so every existing mode above renders
// exactly what it did before and the assertions written against them stand.
//
// `rich` is the case the redesign exists for: enough skills to need collapsing,
// a project description long enough to need a preview, an experience with no
// duration (which must not grow an invented one), and a certification still in
// progress. `partial` is the awkward middle -- entries but no direction, and no
// certifications -- which is what produced the old page's three-empty-sentence
// card.
const careerMode = new URLSearchParams(location.search).get('career');

const LONG_PROJECT_DESCRIPTION =
  'Built a convolutional model for ECG arrhythmia classification on the MIT-BIH database, covering the full pipeline from signal preprocessing and beat segmentation through to model training, evaluation and per-class error analysis across the five AAMI categories.';

if (careerMode === 'rich' || careerMode === 'partial') {
  const rich = careerMode === 'rich';
  // The Details rows, populated. `rich` is also the switching-majors case, so
  // the sentinel's two readings are both reachable from a fixture: `rich`
  // renders a real intended major, `partial` keeps the base 'N/A' and must
  // render "Not switching majors" rather than echoing the sentinel back.
  if (rich) profile.academics.summary.major_intended = 'Data Science';
  profile.career = {
    confirmed: true,
    target_roles: rich ? ['AI Engineer', 'ML Engineer', 'Robotics Engineer'] : [],
    interests: rich ? ['Physical AI', 'Robotics', 'LLM Systems'] : [],
    career_goals: rich
      ? 'Build intelligent systems at the intersection of AI and hardware, and eventually lead a small team doing the same.'
      : null,
    geographic_preference: rich ? 'Austin, TX' : null,
    ai_anxiety_level: rich ? 'moderate' : null,
    skills: {
      technical: [
        'Large Language Models', 'Generative AI', 'Prompt Engineering', 'Retrieval-Augmented Generation',
        'NLP', 'Computer Vision', 'Python', 'PyTorch', 'CUDA', 'Triton', 'C++', 'Bash',
        'TypeScript', 'React', 'PostgreSQL', 'Docker', 'Kubernetes', 'AWS', 'NumPy', 'pandas',
        'scikit-learn', 'Vector Databases',
      ],
      soft: rich ? ['Written communication', 'Mentoring'] : [],
      ai_exposure: null,
    },
    certifications: rich
      ? [
          { name: 'NVIDIA Certified Associate', issuer: 'NVIDIA', status: 'completed', date: '2025', source: 'resume_parse' },
          { name: 'AWS Cloud Practitioner', issuer: null, status: 'in_progress', date: null, source: 'resume_parse' },
        ]
      : [],
    work_experience: [
      { employer: 'Littlebird', role: 'AI Intern', duration: '2025 – Present', location: 'Remote', description: 'Built retrieval tooling for a document assistant, and a profiling harness that cut per-experiment setup from about forty minutes to under five.', skills_gained: ['RAG', 'PyTorch'], source: 'resume_parse' },
      { employer: 'Aggie Data Science Club', role: 'Co-Project Manager', duration: null, location: null, description: null, skills_gained: [], source: 'resume_parse' },
      { employer: '10Spy', role: 'Intern', duration: 'Summer 2024', location: null, description: null, skills_gained: [], source: 'resume_parse' },
    ],
    projects: [
      { name: 'Deep Learning for Arrhythmia Classification', timeframe: 'Spring 2025', description: LONG_PROJECT_DESCRIPTION, tools: ['PyTorch', 'NumPy', 'MIT-BIH'], source: 'resume_parse' },
      { name: 'Campus Scheduler', timeframe: null, description: 'A React app for course planning.', tools: [], source: 'manual' },
    ],
  };
  profile.completeness.career = {
    confirmed_profile: true,
    target_role_present: rich,
    skills_present: true,
    certifications_present: rich,
    work_experience_present: true,
    projects_present: true,
    ready_for_career_features: rich,
  };
}

// THE CASE THE PER-FIELD SPLIT EXISTS FOR: interests, but no target roles.
// The old section-level gate counted this profile as having a career
// direction, so the page printed the interests and said nothing whatsoever
// about the missing target roles -- the one field FIT, GAP and SHIFT all
// require. Neither `rich` (both present) nor `bare` (neither present) can
// catch that, because the bug only appears when the two disagree.
if (careerMode === 'lopsided') {
  profile.career = {
    confirmed: true,
    target_roles: [],
    interests: ['Physical AI', 'Robotics'],
    career_goals: null, geographic_preference: null, ai_anxiety_level: 'not_sure',
    skills: { technical: ['Python'], soft: [], ai_exposure: null },
    certifications: [], work_experience: [], projects: [],
  };
  profile.completeness.career = {
    confirmed_profile: true, target_role_present: false, skills_present: true,
    certifications_present: false, work_experience_present: false, projects_present: false,
    ready_for_career_features: false,
  };
}

// A confirmed career profile with nothing in it -- the state that used to
// render five empty rectangles. The identity facts are cleared here too, so
// this is the fixture where every Details row is absent at once.
if (careerMode === 'bare') {
  profile.identity.expected_graduation = null;
  profile.academics.summary.major_current = null;
  profile.academics.summary.major_intended = null;
  profile.career = {
    confirmed: true,
    target_roles: [], interests: [], career_goals: null, geographic_preference: null, ai_anxiety_level: null,
    skills: { technical: [], soft: [], ai_exposure: null },
    certifications: [], work_experience: [], projects: [],
  };
  profile.completeness.career = {
    confirmed_profile: true, target_role_present: false, skills_present: false,
    certifications_present: false, work_experience_present: false, projects_present: false,
    ready_for_career_features: false,
  };
}

const session = { access_token: 'real-access-token' } as Session;
const context = {
  profile: null, slug: null, loading: false, profileLoading: false, sessionLoading: false,
  login: async () => {}, logout: () => {}, updateCareer: async () => {}, resetCareer: async () => {},
  session, user: null, isPasswordRecovery: false, signInWithPassword: async () => {}, requestPasswordReset: async () => {}, confirmPasswordReset: async () => {}, signUpWithPassword: async () => 'authenticated', signOutSession: async () => {},
  studentAccount: { status: 'ready', profile: { student: { id: 'student-real', name: profile.identity.name, institution: profile.institution.name }, career: null, intelligence_profile: profile }, message: null },
  refreshStudentAccount: () => {},
  reloadStudentProfile: async () => { document.body.dataset.profileReloaded = 'yes'; },
} as AuthContextValue;

// mode=profile-complete reaches the /profile/complete page, so the batch host
// is exercised as a page and not only as the modal's contents. Both render the
// same ProfileCompletionForm, which is exactly what the field extraction has
// to keep true -- if the two hosts ever diverge, one of them breaks silently.
const app = mode === 'error'
  ? <StudentAccountProblem studentAccount={{ status: 'error', profile: null, message: 'Profile API failed.' }} onRetry={() => document.body.dataset.retried = 'yes'} onSignOut={() => {}} />
  : mode === 'profile-complete'
    ? (
      <AuthContext.Provider value={context}>
        <MemoryRouter initialEntries={['/profile/complete?field=student.expected_graduation']}>
          <ProfileCompletionPage />
        </MemoryRouter>
      </AuthContext.Provider>
    )
    // BrowserRouter, not MemoryRouter: AuthenticatedDashboard's nav state now
    // lives in the URL (useUrlParams), and MemoryRouter's history is isolated
    // from the real address bar -- a Playwright test reading page.url() would
    // never see it change. BrowserRouter keeps this preview's query string
    // real, same as the production app.
    : <AuthContext.Provider value={context}><BrowserRouter><AuthenticatedDashboard /></BrowserRouter></AuthContext.Provider>;

// This harness substitutes AuthContext.Provider directly instead of
// rendering the real AuthProvider, so AuthProvider's own institution-theming
// effect (AuthContext.tsx's institutionId effect, ~lines 312-329) never runs
// here -- ?institution= previously had no visible effect on the page's
// accent color. Driven explicitly here, by name rather than id: this
// harness's profile.institution.id ('institution-real') is a placeholder,
// not a real institutions.id foreign key, so fetchInstitutionThemeById would
// always miss -- fetchInstitutionThemeByName is the same fallback
// AuthContext itself uses for name-only demo fixtures.
void fetchInstitutionThemeByName(institution).then(applyInstitutionTheme);

ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode>{app}</React.StrictMode>);
