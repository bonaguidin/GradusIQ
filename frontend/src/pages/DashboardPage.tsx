import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { AcademicSnapshot } from '../components/AcademicSnapshot';
import { DemoCourseLifecyclePreview } from '../components/DemoCourseLifecyclePreview';
import { CourseDiscoveryPanel } from '../components/CourseDiscoveryPanel';
import { DegreePlannerSummary } from '../components/DegreePlannerSummary';
import { DegreeSchedulePanel } from '../components/DegreeSchedulePanel';
import { RequirementSatisfactionPanel } from '../components/RequirementSatisfactionPanel';
import type { DegreeScheduleResponse } from '../api/degreeSchedule.mjs';
import { GapAnalysisPanel } from '../components/GapAnalysisPanel';
import { FitAnalysisPanel } from '../components/FitAnalysisPanel';
import { ShiftAnalysisPanel } from '../components/ShiftAnalysisPanel';
import { TermPlanner } from '../components/TermPlanner';
import { CareerProfile, type CareerEditing, type CareerFieldFocus } from '../components/career/CareerProfile';
import { ProfileChecklist } from '../components/career/ProfileChecklist';
import { ProfileCompletionContext, type ProfileFieldRequest } from '../components/profile/ProfileCompletionContext';
import { analyzeFit, analyzeGap, analyzeShift } from '../api/analysis';
import { useCachedAnalysisRun } from '../hooks/useCachedAnalysisRun';
import { buildDashboardViewModel } from '../data/dashboardViewModel';
import { missingChecklistFields } from '../lib/profileChecklist';
import { applyDemoProfileChanges, buildDemoIntelligenceProfile } from '../data/demoIntelligenceProfile';
import { ensureDemoPlanningStore, snapshotDemoCourseRecords } from '../data/demoPlanningStore';
import type { ProfileCompleteness } from '../types/student';
import { ChatPanel } from '../components/ChatPanel';
import { GuidedTour } from '../components/GuidedTour';
import { AuthenticatedDashboard } from './AuthenticatedDashboard';

// ── Types ──────────────────────────────────────────────────────────────────

type NavSection = 'overview' | 'academic' | 'career';

// 'overview' is each parent's own default view -- what the top-level nav item
// itself renders -- not a visible child tab. Mirrors AuthenticatedDashboard.tsx's
// sub-tab structure exactly, so a demo visitor sees the same nav shape a real
// student does.
type AcademicSubTab = 'overview' | 'gpa-calculator' | 'course-discovery';
type CareerSubTab = 'overview' | 'intelligence' | 'job-search' | 'profile';

const ACADEMIC_SUB_TABS: Array<{ key: AcademicSubTab; label: string }> = [
  { key: 'gpa-calculator', label: 'GPA Calculator' },
  { key: 'course-discovery', label: 'Course Discovery' },
];

const CAREER_SUB_TABS: Array<{ key: CareerSubTab; label: string }> = [
  { key: 'intelligence', label: 'Career Intelligence' },
  { key: 'job-search', label: 'Job Search' },
  { key: 'profile', label: 'Career Profile' },
];

// ── Readiness Rail (sidebar signature element) ─────────────────────────────

const FEATURES = [
  { key: 'FIT'   as const, label: 'FIT',   subtitle: 'Role Explorer' },
  { key: 'GAP'   as const, label: 'GAP',   subtitle: 'Readiness Check' },
  { key: 'SHIFT' as const, label: 'SHIFT', subtitle: 'Trend Guidance' },
] as const;

function ReadinessRail({ completeness }: { completeness: ProfileCompleteness }) {
  const overall = Math.round((completeness.overall ?? 0) * 100);
  const academic = Math.round((completeness.academic ?? 0) * 100);
  const career   = Math.round((completeness.career   ?? 0) * 100);

  return (
    <div className="readiness-rail">
      <div className="readiness-heading">Readiness</div>

      <div className="readiness-overall">
        <span className="readiness-pct">{overall}%</span>
        <span className="readiness-pct-label">overall</span>
      </div>

      {/* FIT / GAP / SHIFT gauge — vertical line connects the dots */}
      <div className="readiness-marks">
        {FEATURES.map(({ key, label, subtitle }) => {
          const ready = completeness.by_feature?.[key]?.ready ?? false;
          return (
            <div
              key={key}
              className={`readiness-mark${ready ? ' readiness-mark--ready' : ''}`}
              aria-label={`${label}: ${ready ? 'ready' : 'incomplete'}`}
            >
              <span className="readiness-mark-name">{label}</span>
              <span className="readiness-mark-label">{subtitle}</span>
              <span className="readiness-mark-status">
                {ready ? 'Ready' : '—'}
              </span>
            </div>
          );
        })}
      </div>

      <div className="readiness-bars">
        {[
          { label: 'Academic', pct: academic },
          { label: 'Career',   pct: career   },
        ].map(({ label, pct }) => (
          <div key={label} className="readiness-bar-row">
            <div className="readiness-bar-header">
              <span className="readiness-bar-label">{label}</span>
              <span className="readiness-bar-pct">{pct}%</span>
            </div>
            <div
              className="readiness-bar-track"
              role="progressbar"
              aria-valuenow={pct}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={`${label} completeness: ${pct}%`}
            >
              <div className="readiness-bar-fill" style={{ width: `${pct}%` }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Overview Section ───────────────────────────────────────────────────────

function OverviewSection() {
  const { profile, resetCareer } = useAuth();
  const [resetting, setResetting] = useState(false);

  if (!profile) return null;

  const { student, profile_completeness, courses } = profile;

  const gradYear = student.expected_graduation
    ? student.expected_graduation.slice(0, 4)
    : null;

  async function handleReset() {
    setResetting(true);
    try {
      await resetCareer();
    } finally {
      setResetting(false);
    }
  }

return (
  <div className="stage-section">
    <ChatPanel />

    {/* Student identity — editorial serif */}
    <div className="overview-header">
        <h1 className="overview-name">{student.name}</h1>
        <div className="overview-vitals">
          <span>{student.major_current}</span>
          <span className="overview-vitals-sep" aria-hidden="true">·</span>
          <span>{student.institution}</span>
          {gradYear && (
            <>
              <span className="overview-vitals-sep" aria-hidden="true">·</span>
              <span>Expected {gradYear}</span>
            </>
          )}
        </div>
      </div>

      {/* Key stats in mono — the instrument feel */}
      <div className="overview-stats">
        <div className="overview-stat">
          <span className="overview-stat-value">
            {student.gpa_current !== null ? student.gpa_current.toFixed(2) : '—'}
          </span>
          <span className="overview-stat-label">GPA</span>
        </div>
        <div className="overview-stat">
          <span className="overview-stat-value">
            {courses.length}
          </span>
          <span className="overview-stat-label">Courses</span>
        </div>
        <div className="overview-stat">
          <span className="overview-stat-value">
            {student.classification}
          </span>
          <span className="overview-stat-label">Standing</span>
        </div>
      </div>

      {/* Two-column grid: feature status + completion */}
      <div className="overview-grid">
        <div className="overview-block">
          <div className="overview-block-title">Feature Readiness</div>
          <div className="overview-feature-list">
            {FEATURES.map(({ key, label, subtitle }) => {
              const ready = profile_completeness.by_feature?.[key]?.ready ?? false;
              return (
                <div key={key} className="overview-feature-row">
                  <span className="overview-feature-name">{label}</span>
                  <span className="overview-feature-desc">{subtitle}</span>
                  <span
                    className={`overview-feature-badge ${
                      ready
                        ? 'overview-feature-badge--ready'
                        : 'overview-feature-badge--pending'
                    }`}
                  >
                    {ready ? 'Ready' : 'Incomplete'}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        <div className="overview-block">
          <div className="overview-block-title">Profile Completeness</div>
          <div className="overview-progress">
            {[
              { label: 'Academic', value: profile_completeness.academic ?? 0 },
              { label: 'Career',   value: profile_completeness.career   ?? 0 },
              { label: 'Overall',  value: profile_completeness.overall  ?? 0 },
            ].map(({ label, value }) => {
              const pct = Math.round(value * 100);
              return (
                <div key={label} className="overview-progress-row">
                  <div className="overview-progress-header">
                    <span className="overview-progress-label">{label}</span>
                    <span className="overview-progress-pct">{pct}%</span>
                  </div>
                  <div
                    className="overview-progress-track"
                    role="progressbar"
                    aria-valuenow={pct}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-label={`${label}: ${pct}%`}
                  >
                    <div
                      className="overview-progress-fill"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Demo reset */}
      <div className="overview-demo">
        <div className="overview-demo-title">Demo Controls</div>
        <p className="overview-demo-note">
          Reset career data to the original profile (clears any localStorage edits).
        </p>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => { void handleReset(); }}
          disabled={resetting}
          aria-busy={resetting}
        >
          {resetting ? 'Resetting…' : 'Reset to original'}
        </button>
      </div>
    </div>
  );
}

// ── Dashboard Page ─────────────────────────────────────────────────────────

const NAV_ITEMS: { key: NavSection; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'academic', label: 'Academic' },
  { key: 'career',   label: 'Career'   },
];

const SECTION_TITLES: Record<NavSection, string> = {
  overview: 'Overview',
  academic: 'Academic Record',
  career:   'Career',
};

export function DashboardPage() {
  const { profile, studentAccount } = useAuth();

  if (!profile && studentAccount.status === 'ready') {
    return <AuthenticatedDashboard />;
  }
  return <DemoDashboardPage />;
}

function DemoDashboardPage() {
  const { profile, logout, slug } = useAuth();
  const navigate = useNavigate();
  const [activeSection, setActiveSection] = useState<NavSection>('overview');
  const [academicSubTab, setAcademicSubTab] = useState<AcademicSubTab>('overview');
  const [careerSubTab, setCareerSubTab] = useState<CareerSubTab>('overview');
  const [railOpen, setRailOpen] = useState(false);
  const [degreeScheduleResult, setDegreeScheduleResult] = useState<DegreeScheduleResponse | null>(null);
  const [fieldFocus, setFieldFocus] = useState<CareerFieldFocus | null>(null);

  // First-run tour: remembered per demo student (localStorage), so it auto-shows
  // once and is replayable on demand via the topbar "?" button.
  const tourSeenKey = slug ? `gradusiq_tour_seen_demo_${slug}` : null;
  const [tourOpen, setTourOpen] = useState<boolean>(() =>
    tourSeenKey ? localStorage.getItem(tourSeenKey) !== '1' : true,
  );

  // The local, StudentIntelligenceProfile-shaped view of this student --
  // feeds buildDashboardViewModel/CareerProfile/ProfileChecklist exactly the
  // way a real account's canonical profile does. CareerProfile edits mutate
  // this via setDemoProfile (see careerEditing below); nothing here is ever
  // sent anywhere.
  const [demoProfile, setDemoProfile] = useState<ReturnType<typeof buildDemoIntelligenceProfile> | null>(null);
  // GPA Calculator's own live course-record list -- separate from
  // demoProfile.academics.courses (a static snapshot) because TermPlanner
  // mutations (drop, current-grade entry) need to be reflected immediately
  // without recomputing GPA client-side. See demoPlanningStore.ts.
  const [demoCourseRecords, setDemoCourseRecords] = useState<ReturnType<typeof snapshotDemoCourseRecords>>([]);

  // Rebuilt once per demo student (keyed on slug, which only changes on a
  // student switch) -- NOT on every render, or a CareerProfile/TermPlanner
  // edit would be silently reverted by an unrelated re-render.
  useEffect(() => {
    if (!profile || !slug) return;
    const built = buildDemoIntelligenceProfile(profile);
    setDemoProfile(built);
    ensureDemoPlanningStore(slug, built.academics.courses, profile.student.institution);
    setDemoCourseRecords(snapshotDemoCourseRecords(slug));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on slug only, see comment above
  }, [slug]);

  const refreshCourseRecords = useCallback(() => {
    if (slug) setDemoCourseRecords(snapshotDemoCourseRecords(slug));
  }, [slug]);

  const identity = useMemo(() => ({ slug, accessToken: null }), [slug]);

  // Same lifted-run pattern AuthenticatedDashboard.tsx uses: one run per
  // feature, read both by the compact Career Overview summary and by the
  // full panel on Career Intelligence, instead of two independent fetches.
  const gapRun = useCachedAnalysisRun('gap', () => analyzeGap(identity));
  const fitRun = useCachedAnalysisRun('fit', () => analyzeFit(identity));
  const shiftRun = useCachedAnalysisRun('shift', () => analyzeShift(identity));

  const requestField = useCallback((request: ProfileFieldRequest) => {
    setActiveSection('career');
    setCareerSubTab('profile');
    setRailOpen(false);
    setFieldFocus({ path: request.path, nonce: Date.now() });
  }, []);

  const careerEditing: CareerEditing = useMemo(
    () => ({
      persist: async (changes) => {
        setDemoProfile((current) => (current ? applyDemoProfileChanges(current, changes) : current));
      },
      onSaved: async () => {},
    }),
    [],
  );

  const dashboard = useMemo(() => (demoProfile ? buildDashboardViewModel(demoProfile) : null), [demoProfile]);
  const missingDetails = useMemo(
    () => (demoProfile ? missingChecklistFields(demoProfile) : []),
    [demoProfile],
  );

  // RequireAuth guarantees profile is non-null here; demoProfile/dashboard lag
  // one effect tick behind on first mount.
  if (!profile || !demoProfile || !dashboard) return null;

  const { student, profile_completeness, career } = profile;

  // Derive two-letter monogram
  const initials = student.name
    .split(' ')
    .filter(Boolean)
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();

  function handleLogout() {
    logout();
    void navigate('/login');
  }

  function navigateTo(section: NavSection) {
    setActiveSection(section);
    // The top-level item IS the overview -- always reset to it, matching
    // AuthenticatedDashboard.tsx's own navigateTo.
    if (section === 'academic') setAcademicSubTab('overview');
    if (section === 'career') setCareerSubTab('overview');
    setRailOpen(false);
  }

  function navigateToAcademicSubTab(tab: AcademicSubTab) {
    setActiveSection('academic');
    setAcademicSubTab(tab);
    setRailOpen(false);
  }

  function navigateToCareerSubTab(tab: CareerSubTab) {
    setActiveSection('career');
    setCareerSubTab(tab);
    setRailOpen(false);
  }

  function handleTourClose(completed: boolean) {
    setTourOpen(false);
    if (tourSeenKey) localStorage.setItem(tourSeenKey, '1');
    // If they bailed early, return to the top of the profile for a clean start.
    if (!completed) setActiveSection('overview');
  }

  return (
    <ProfileCompletionContext.Provider value={requestField}>
    <div className="shell">
      {/* First-run onboarding tour — carousel that walks the tabs */}
      {tourOpen && (
        <GuidedTour onNavigate={setActiveSection} onClose={handleTourClose} />
      )}

      {/* Mobile overlay — click to close rail */}
      {railOpen && (
        <div
          className="rail-overlay"
          onClick={() => setRailOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* ── Left Rail ── */}
      <aside
        className={`rail${railOpen ? ' rail--open' : ''}`}
        aria-label="Dashboard navigation"
      >
        {/* Identity */}
        <div className="rail-identity">
          <div className="rail-monogram" aria-hidden="true">
            {initials}
          </div>
          <div className="rail-name">{student.name}</div>
          <div className="rail-meta">
            <span>{student.classification}</span>
            <span className="rail-dot" aria-hidden="true">·</span>
            <span className="rail-gpa">
              {student.gpa_current !== null ? student.gpa_current.toFixed(2) : '—'}
            </span>
          </div>
        </div>

        {/* Navigation */}
        <nav className="rail-nav" aria-label="Dashboard sections">
          {NAV_ITEMS.map(({ key, label }) => (
            <div key={key} className="rail-nav-group">
              <button
                type="button"
                className={`rail-item${activeSection === key ? ' rail-item--active' : ''}`}
                onClick={() => navigateTo(key)}
                aria-current={activeSection === key ? 'page' : undefined}
              >
                {label}
              </button>
              {key === 'academic' && activeSection === 'academic' && (
                <div className="rail-subnav" role="group" aria-label="Academic sections">
                  {ACADEMIC_SUB_TABS.map((sub) => (
                    <button
                      key={sub.key}
                      type="button"
                      className={`rail-subitem${academicSubTab === sub.key ? ' rail-subitem--active' : ''}`}
                      onClick={() => navigateToAcademicSubTab(sub.key)}
                      aria-current={academicSubTab === sub.key ? 'page' : undefined}
                    >
                      {sub.label}
                    </button>
                  ))}
                </div>
              )}
              {key === 'career' && activeSection === 'career' && (
                <div className="rail-subnav" role="group" aria-label="Career sections">
                  {CAREER_SUB_TABS.map((sub) => (
                    <button
                      key={sub.key}
                      type="button"
                      className={`rail-subitem${careerSubTab === sub.key ? ' rail-subitem--active' : ''}`}
                      onClick={() => navigateToCareerSubTab(sub.key)}
                      aria-current={careerSubTab === sub.key ? 'page' : undefined}
                    >
                      {sub.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
        </nav>

        {/* Readiness Rail — signature instrument element */}
        <ReadinessRail completeness={profile_completeness} />

        {/* Footer — logout */}
        <div className="rail-footer">
          <button
            type="button"
            className="rail-logout"
            onClick={handleLogout}
          >
            Logout
          </button>
        </div>
      </aside>

      {/* ── Main Stage ── */}
      <div className="stage">
        {/* Topbar */}
        <header className="topbar">
          <button
            type="button"
            className="topbar-menu"
            onClick={() => setRailOpen(true)}
            aria-label="Open navigation"
            aria-expanded={railOpen}
          >
            {/* Hamburger icon via CSS pseudo-elements + span */}
            <span className="topbar-menu-icon" aria-hidden="true">
              <span />
            </span>
          </button>
          <h2 className="topbar-title">{SECTION_TITLES[activeSection]}</h2>
          <button
            type="button"
            className="topbar-help"
            onClick={() => setTourOpen(true)}
            aria-label="Replay the new-user tour"
            title="Take the tour"
          >
            ?
          </button>
        </header>

        {/* Content — keyed on activeSection so entrance animation replays */}
        <main className="stage-main">
          <div className="stage-inner">
            {activeSection === 'overview' && (
              <OverviewSection key="overview" />
            )}

            {activeSection === 'academic' && academicSubTab === 'overview' && (
              <div key="academic-overview" className="stage-section">
                <h2 className="academic-section-heading">Academic Overview</h2>
                <AcademicSnapshot
                  courses={profile.courses}
                  enrollments={profile.enrollments}
                  assignments={profile.assignments}
                  submissions={profile.submissions}
                  examTopicTags={profile.examTopicTags}
                />
                <DemoCourseLifecyclePreview rows={profile.course_lifecycle_preview ?? []} />
              </div>
            )}

            {activeSection === 'academic' && academicSubTab === 'gpa-calculator' && (
              <div key="academic-gpa" className="stage-section">
                <h2 className="academic-section-heading">GPA Calculator</h2>
                <div className="overview-stats">
                  <div className="overview-stat"><span className="overview-stat-value">{dashboard.officialGpa?.toFixed(2) ?? '—'}</span><span className="overview-stat-label">Official GPA</span></div>
                  <div className="overview-stat"><span className="overview-stat-value">{dashboard.projectedGpa?.toFixed(2) ?? '—'}</span><span className="overview-stat-label">Projected GPA</span></div>
                  <div className="overview-stat"><span className="overview-stat-value">{dashboard.earnedHours}</span><span className="overview-stat-label">Earned Hours</span></div>
                </div>
                <p className="gpa-projection-note">
                  {dashboard.inProgressWithCurrentGradeCount > 0
                    ? `Based on current grades in ${dashboard.inProgressWithCurrentGradeCount} in-progress course${dashboard.inProgressWithCurrentGradeCount === 1 ? '' : 's'}.`
                    : 'Enter current grades below to see your projected GPA.'}
                </p>
                <TermPlanner
                  slug={identity.slug}
                  accessToken={identity.accessToken}
                  courses={demoCourseRecords}
                  onCourseRecordsChanged={refreshCourseRecords}
                />
              </div>
            )}

            {activeSection === 'academic' && academicSubTab === 'course-discovery' && (
              <div key="academic-course-discovery" className="stage-section">
                {career && career.target_roles.length > 0 && (
                  <CourseDiscoveryPanel targetRoles={career.target_roles} />
                )}
                {/* DegreeSchedulePanel/RequirementSatisfactionPanel resolve real
                    data only for the one demo student whose institution+major
                    match a wired local program (SMU Computer Science) --
                    every other demo student sees the same "not available yet"
                    state a real student without program data gets. Career
                    Optimization stays out of the demo (DegreeSchedulePanel
                    already gates it on identity.slug). */}
                <div className="degree-planner-flow">
                  <DegreePlannerSummary
                    institution={student.institution}
                    major={student.major_current ?? student.major_intended}
                    expectedGraduation={student.expected_graduation}
                    schedule={degreeScheduleResult}
                  />
                  <DegreeSchedulePanel
                    targetRole={career?.target_roles?.[0]}
                    onResult={setDegreeScheduleResult}
                  />
                  <RequirementSatisfactionPanel />
                </div>
              </div>
            )}

            {activeSection === 'career' && careerSubTab === 'overview' && (
              <div key="career-overview" className="stage-section">
                <h2 className="career-section-heading">Career Overview</h2>
                <ProfileChecklist
                  missing={missingDetails}
                  onJump={(field, trigger) => { requestField({ path: field.path, trigger }); }}
                />
                <div className="career-overview-target">
                  <span>Primary target role</span>
                  <strong>{dashboard.career.target_roles[0] ?? 'Not provided'}</strong>
                </div>
                <div className="career-overview-grid">
                  {([
                    ['Role Fit', fitRun.state],
                    ['Readiness', gapRun.state],
                    ['Trend Guidance', shiftRun.state],
                  ] as const).map(([label, state]) => (
                    <section className="career-overview-summary" key={label}>
                      <h3>{label}</h3>
                      <p>{state.phase === 'done' ? state.result.summary : state.phase === 'loading' ? 'Analysis in progress.' : state.phase === 'transport-error' ? 'Analysis unavailable.' : 'No analysis has been run yet.'}</p>
                    </section>
                  ))}
                </div>
              </div>
            )}

            {activeSection === 'career' && careerSubTab === 'intelligence' && (
              <div key="career-intelligence" className="stage-section career-subtab-panel career-intelligence">
                <h2 className="career-section-heading">Career Intelligence</h2>
                <p className="career-intelligence-role">Target role: <strong>{dashboard.career.target_roles[0] ?? 'Not provided'}</strong></p>
                <section className="career-intelligence-section"><FitAnalysisPanel run={fitRun} /></section>
                <section className="career-intelligence-section"><GapAnalysisPanel run={gapRun} /></section>
                <section className="career-intelligence-section"><ShiftAnalysisPanel run={shiftRun} /></section>
              </div>
            )}

            {activeSection === 'career' && careerSubTab === 'job-search' && (
              <div key="career-job-search" className="stage-section">
                <h2 className="career-section-heading">Job Search</h2>
                <div className="job-search-shell">
                  <label>Target role<select defaultValue={dashboard.career.target_roles[0] ?? ''} disabled={dashboard.career.target_roles.length === 0}>{dashboard.career.target_roles.length === 0 && <option value="">No target role provided</option>}{dashboard.career.target_roles.map((role) => <option key={role}>{role}</option>)}</select></label>
                  <label>Location<input value={dashboard.career.geographic_preference ?? ''} placeholder="No location preference provided" readOnly /></label>
                  <button type="button" className="btn btn-primary" disabled>Search Jobs</button>
                </div>
                <div className="real-empty"><h3>Live job search is not connected yet</h3><p>Your target role and location are ready, but this repository does not yet expose a production job-search service.</p></div>
              </div>
            )}

            {activeSection === 'career' && careerSubTab === 'profile' && (
              <div key="career-profile" className="stage-section career-subtab-panel">
                <ProfileChecklist
                  missing={missingDetails}
                  onJump={(field, trigger) => { requestField({ path: field.path, trigger }); }}
                />
                <div className="career-profile-block">
                  <h2 className="career-section-heading">Career Profile</h2>
                  <CareerProfile
                    career={dashboard.career}
                    details={{
                      expectedGraduation: dashboard.expectedGraduation,
                      majorCurrent: dashboard.majorCurrent,
                      majorIntended: dashboard.majorIntended,
                    }}
                    editing={careerEditing}
                    focus={fieldFocus}
                  />
                </div>
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
    </ProfileCompletionContext.Provider>
  );
}
