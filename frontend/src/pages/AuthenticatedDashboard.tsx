import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { analyzeCourseDiscovery, analyzeFit, analyzeGap, analyzeShift } from '../api/analysis';
import { useAnalysisRun } from '../hooks/useAnalysisRun';
import { useCachedAnalysisRun } from '../hooks/useCachedAnalysisRun';
import { ChatPanel } from '../components/ChatPanel';
import { GuidedTour } from '../components/GuidedTour';
import { DashboardSuccessNotice } from '../components/DashboardSuccessNotice';
import { CourseDiscoveryPanel } from '../components/CourseDiscoveryPanel';
import { RequirementSatisfactionPanel } from '../components/RequirementSatisfactionPanel';
import { DegreeProgressRing } from '../components/DegreeProgressRing';
import { fetchRequirementSatisfaction, isSkippedRequirementSatisfaction } from '../api/requirementSatisfaction.mjs';
import { countSatisfiedLeafGroups } from '../lib/requirementProgress.mjs';
import { pickTopRole, pickBiggestGap } from '../lib/careerReadinessCards.mjs';
import { currentTermSnapshot } from '../lib/currentTermSnapshot.mjs';
import { DegreeSchedulePanel } from '../components/DegreeSchedulePanel';
import { DegreePlannerSummary } from '../components/DegreePlannerSummary';
import type { DegreeScheduleResponse } from '../api/degreeSchedule.mjs';
import { FitAnalysisPanel, FIT_LEVEL_LABEL } from '../components/FitAnalysisPanel';
import { GapAnalysisPanel } from '../components/GapAnalysisPanel';
import { ShiftAnalysisPanel } from '../components/ShiftAnalysisPanel';
import { TermPlanner } from '../components/TermPlanner';
import { GradeCalculatorPanel } from '../components/GradeCalculatorPanel';
import { CareerProfile, type CareerFieldFocus } from '../components/career/CareerProfile';
import { updateProfile } from '../api/profile';
import { ProfileChecklist } from '../components/career/ProfileChecklist';
import { ProfileCompletionContext, type ProfileFieldRequest } from '../components/profile/ProfileCompletionContext';
import { buildDashboardViewModel } from '../data/dashboardViewModel';
import { missingChecklistFields } from '../lib/profileChecklist';

type NavSection = 'overview' | 'academic' | 'career';

const NAV_ITEMS: Array<{ key: NavSection; label: string }> = [
  { key: 'overview', label: 'Overview' },
  { key: 'academic', label: 'Academic' },
  { key: 'career', label: 'Career' },
];

type CareerSubTab = 'overview' | 'intelligence' | 'job-search' | 'profile';

const CAREER_SUB_TABS: Array<{ key: CareerSubTab; label: string }> = [
  { key: 'intelligence', label: 'Career Intelligence' },
  { key: 'job-search', label: 'Job Search' },
  { key: 'profile', label: 'Career Profile' },
];

// 'overview' is Academic's own default view -- what the top-level Academic
// nav item itself renders -- not a visible child tab. Only these two appear
// as nested nav items under Academic.
type AcademicSubTab = 'overview' | 'gpa-calculator' | 'grade-calculator' | 'course-discovery';

const ACADEMIC_SUB_TABS: Array<{ key: AcademicSubTab; label: string }> = [
  { key: 'gpa-calculator', label: 'GPA Calculator' },
  { key: 'grade-calculator', label: 'Grade Calculator' },
  { key: 'course-discovery', label: 'Course Discovery' },
];

// First-run tour is remembered per user (localStorage), so it auto-shows once
// and the "?" button replays it on demand. A profile field could hold this
// later; localStorage keeps it demo-simple with no migration.
const TOUR_SEEN_PREFIX = 'gradusiq_tour_seen_';

export function AuthenticatedDashboard() {
  const { studentAccount, signOutSession, session, slug, reloadStudentProfile } = useAuth();
  const tourSeenKey = session?.user?.id ? `${TOUR_SEEN_PREFIX}${session.user.id}` : null;
  const [tourOpen, setTourOpen] = useState<boolean>(() =>
    tourSeenKey ? localStorage.getItem(tourSeenKey) !== '1' : false,
  );
  // The term view reads planned_courses and the catalog through the session
  // bearer token. Absent one, the section falls back to the flat course list
  // below rather than rendering an empty planner.
  const accessToken = session?.access_token ?? null;
  const navigate = useNavigate();
  const [activeSection, setActiveSection] = useState<NavSection>('overview');
  const [careerSubTab, setCareerSubTab] = useState<CareerSubTab>('overview');
  const [academicSubTab, setAcademicSubTab] = useState<AcademicSubTab>('overview');
  const [railOpen, setRailOpen] = useState(false);
  const [fieldFocus, setFieldFocus] = useState<CareerFieldFocus | null>(null);
  const [profileSaved, setProfileSaved] = useState(false);
  const [degreeScheduleResult, setDegreeScheduleResult] = useState<DegreeScheduleResponse | null>(null);
  // Lifted out of GapAnalysisPanel/FitAnalysisPanel/ShiftAnalysisPanel (each
  // still owns its own internal useCachedAnalysisRun by default) so Career
  // Overview and Career Intelligence read the same independent run states.
  // useCachedAnalysisRun keeps the existing cache behavior for each feature.
  const gapRun = useCachedAnalysisRun('gap', () => analyzeGap({ slug, accessToken }));
  const fitRun = useCachedAnalysisRun('fit', () => analyzeFit({ slug, accessToken }));
  const shiftRun = useCachedAnalysisRun('shift', () => analyzeShift({ slug, accessToken }));
  // Overview's degree-progress ring needs the same requirement-satisfaction
  // tree RequirementSatisfactionPanel renders under Academic -- lifted here
  // instead of duplicated inside the panel, same lifted-state shape as
  // gapRun/fitRun/shiftRun above. The endpoint is a plain authenticated read
  // (no AI work, sub-second -- see requirementSatisfaction.mjs), so firing it
  // on every dashboard load costs nothing like a GAP/FIT live run would.
  const requirementRun = useAnalysisRun(useCallback(
    () => fetchRequirementSatisfaction({ slug, accessToken }),
    [slug, accessToken],
  ));
  const requirementTrigger = requirementRun.trigger;
  const requirementStarted = useRef(false);
  useEffect(() => {
    if (requirementStarted.current) return;
    requirementStarted.current = true;
    requirementTrigger();
  }, [requirementTrigger]);
  const canonical = studentAccount.profile?.intelligence_profile;
  const dashboard = useMemo(
    () => (canonical ? buildDashboardViewModel(canonical) : null),
    [canonical],
  );
  // Lifted out of CourseDiscoveryPanel (which still owns its own internal
  // useAnalysisRun by default) so Academic Overview's compact summary can
  // read the exact same run/result the full Course Discovery view shows --
  // one run, reflected in both places, instead of a second independent
  // fetch or a duplicate result store. No caching hook (unlike GAP/FIT/
  // SHIFT): course_discovery is not in the server-side analysis cache, so
  // this stays a plain useAnalysisRun exactly as CourseDiscoveryPanel used
  // internally before.
  const [courseDiscoverySelectedRole, setCourseDiscoverySelectedRole] = useState(
    () => canonical?.career.target_roles[0] ?? '',
  );
  const courseDiscoveryRun = useAnalysisRun(() =>
    analyzeCourseDiscovery(
      { slug, accessToken },
      (canonical?.career.target_roles.length ?? 0) > 1 ? courseDiscoverySelectedRole : null,
    ),
  );
  const courseDiscoveryState = courseDiscoveryRun.state;
  const courseDiscoverySuccess = useMemo(
    () =>
      courseDiscoveryState.phase === 'done' && courseDiscoveryState.result.status === 'success'
        ? courseDiscoveryState.result.data
        : null,
    [courseDiscoveryState],
  );
  // Computed from the profile in hand, not from a skipped analysis: the
  // checklist has to be right before anything has been run, which is the whole
  // reason it is not built out of the panels' own missing_fields.
  const missingDetails = useMemo(
    () => (canonical ? missingChecklistFields(canonical) : []),
    [canonical],
  );
  // "What am I taking right now" -- in-progress course records already on
  // the profile, with the term(s) they belong to. No separate fetch: term
  // dates/status (and planned coursework) are GPA Calculator's concern via
  // TermPlanner, not Overview's or Academic Overview's. Shared by Academic
  // Overview's "Current coursework" section and Overview's current-term
  // card -- see currentTermSnapshot.mjs for why this is a union across
  // simultaneous in-progress terms, not a single-term pick.
  const currentTerm = useMemo(
    () => (dashboard ? currentTermSnapshot({ courses: dashboard.courses, terms: dashboard.terms }) : null),
    [dashboard],
  );
  const academicOverviewCurrentCourses = currentTerm?.courses ?? [];
  const academicOverviewCurrentTermLabel = currentTerm?.termLabel ?? null;

  /**
   * Send the student to the field, wherever they asked from.
   *
   * The one handler behind both entry points -- the checklist and a skipped
   * analysis's per-gap link -- so the two cannot answer the same request
   * differently. Switching to the Career tab first is what makes it work from
   * anywhere: the field only exists on that tab, and the request is worthless
   * if it lands on a section that does not render it.
   */
  const requestField = useCallback((request: ProfileFieldRequest) => {
    setActiveSection('career');
    // The field only renders inside CareerProfile, which now lives on the
    // Career Profile child rather than directly on the Career overview — so a
    // skipped-analysis "Add this" link has to land the student there too,
    // not just on whichever Career sub-tab happened to be open.
    setCareerSubTab('profile');
    setRailOpen(false);
    // A new object every time, so asking twice for the same field works.
    setFieldFocus({ path: request.path, nonce: Date.now() });
  }, []);

  if (!dashboard) return null;

  const displayName = dashboard.name ?? 'Student';
  const major = dashboard.majorCurrent ?? dashboard.majorIntended;
  const readiness = dashboard.completeness.overall;

  // 'skipped' (no program to evaluate against yet) collapses to the same
  // { satisfied: 0, total: 0 } as 'loading'/'transport-error' -- the ring
  // renders its dash for all three, since none of them is a real 0-of-0.
  const requirementGroups =
    requirementRun.state.phase === 'done' && !isSkippedRequirementSatisfaction(requirementRun.state.result)
      ? requirementRun.state.result.groups
      : [];
  const degreeProgress = countSatisfiedLeafGroups(requirementGroups);

  const fitData =
    fitRun.state.phase === 'done' && fitRun.state.result.status === 'success' ? fitRun.state.result.data : null;
  const topRole = pickTopRole(fitData);

  const gapData =
    gapRun.state.phase === 'done' && gapRun.state.result.status === 'success' ? gapRun.state.result.data : null;
  const biggestGap = pickBiggestGap(gapData);

  async function handleLogout() {
    await signOutSession();
    void navigate('/login');
  }

  function navigateTo(section: NavSection) {
    setActiveSection(section);
    // The top-level Academic item IS the overview -- clicking it, whether
    // arriving fresh or returning from a child, always resets to it rather
    // than leaving whichever child was last open.
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

  function handleTourClose() {
    setTourOpen(false);
    if (tourSeenKey) localStorage.setItem(tourSeenKey, '1');
  }

  // The tour ends on these; each marks the tour seen (via onClose) then routes.
  const tourEndActions = [
    { label: 'Add transcript', onClick: () => { void navigate('/transcript'); } },
    { label: 'Add resume', onClick: () => { void navigate('/resume'); } },
  ];

  return (
    <ProfileCompletionContext.Provider value={requestField}><div className="shell" data-dashboard-source="authenticated">
      {/* First-run onboarding tour — carousel that walks the tabs and ends on
          the transcript/resume upload CTAs. */}
      {tourOpen && (
        <GuidedTour
          onNavigate={setActiveSection}
          onClose={handleTourClose}
          endActions={tourEndActions}
        />
      )}
      {railOpen && <div className="rail-overlay" onClick={() => setRailOpen(false)} aria-hidden="true" />}
      <aside className={`rail${railOpen ? ' rail--open' : ''}`} aria-label="Dashboard navigation">
        <div className="rail-identity">
          <div className="rail-monogram" aria-hidden="true">{dashboard.initials || 'ST'}</div>
          <div className="rail-name">{displayName}</div>
          <div className="rail-meta">
            <span>{dashboard.classification ?? 'Student'}</span>
            <span className="rail-dot" aria-hidden="true">·</span>
            <span className="rail-gpa">{dashboard.officialGpa?.toFixed(2) ?? '—'}</span>
          </div>
        </div>
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
              {/* Parent clicks render their internal overview; only the
                  user-facing destinations appear as nested children. */}
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
        <div className="readiness-rail real-readiness">
          <div className="readiness-heading">Readiness</div>
          <div className="readiness-overall">
            <span className="readiness-state">{readiness}</span>
            <span className="readiness-pct-label">overall profile</span>
          </div>
          <div className="readiness-marks">
            <div className={`readiness-mark${dashboard.completeness.academics.ready_for_academic_features ? ' readiness-mark--ready' : ''}`}>
              <span className="readiness-mark-name">Academic</span>
              <span className="readiness-mark-status">{dashboard.completeness.academics.ready_for_academic_features ? 'Ready' : 'Incomplete'}</span>
            </div>
            <div className={`readiness-mark${dashboard.completeness.career.ready_for_career_features ? ' readiness-mark--ready' : ''}`}>
              <span className="readiness-mark-name">Career</span>
              <span className="readiness-mark-status">{dashboard.completeness.career.ready_for_career_features ? 'Ready' : 'Incomplete'}</span>
            </div>
          </div>
        </div>
        <div className="rail-footer">
          <button type="button" className="rail-logout" onClick={() => { void handleLogout(); }}>Logout</button>
        </div>
      </aside>

      <div className="stage">
        <header className="topbar">
          <button type="button" className="topbar-menu" onClick={() => setRailOpen(true)} aria-label="Open navigation" aria-expanded={railOpen}>
            <span className="topbar-menu-icon" aria-hidden="true"><span /></span>
          </button>
          <h2 className="topbar-title">{NAV_ITEMS.find((item) => item.key === activeSection)?.label}</h2>
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
        <main className="stage-main">
          <div className="stage-inner">
            {/* Above the section content and inside the normal flow: it is an
                acknowledgement, not an interruption, so nothing overlays,
                blocks, or steals focus. Outside the section switch so changing
                tabs does not re-mount (and re-announce) it. */}
            <DashboardSuccessNotice />

            {activeSection === 'overview' && (
              <div className="stage-section">
                <ChatPanel />
                <div className="overview-header">
                  <h1 className="overview-name">{displayName}</h1>
                  <div className="overview-vitals">
                    <span>{major ?? 'Major not provided'}</span>
                    <span className="overview-vitals-sep" aria-hidden="true">·</span>
                    <span>{dashboard.institutionName ?? 'Institution not provided'}</span>
                  </div>
                </div>
                <div className="overview-stats">
                  <div className="overview-stat"><span className="overview-stat-value">{dashboard.officialGpa?.toFixed(2) ?? '—'}</span><span className="overview-stat-label">Official GPA</span></div>
                  <div className="overview-stat"><span className="overview-stat-value">{dashboard.courses.length}</span><span className="overview-stat-label">Confirmed Courses</span></div>
                  <div className="overview-stat"><span className="overview-stat-value readiness-state">{readiness}</span><span className="overview-stat-label">Profile Status</span></div>
                  <DegreeProgressRing satisfied={degreeProgress.satisfied} total={degreeProgress.total} />
                </div>
                <div className="overview-grid">
                  <section className="overview-block">
                    <div className="overview-block-title">Academic readiness</div>
                    <p>{dashboard.completeness.academics.transcript_data_present ? `${String(dashboard.courses.length)} confirmed courses across ${String(dashboard.terms.length)} terms.` : 'No confirmed transcript data yet.'}</p>
                    {!dashboard.completeness.academics.transcript_data_present && <Link to="/transcript" className="btn btn-primary btn-sm">Upload transcript</Link>}
                    <div className="academic-readiness-cards">
                      <div>
                        <div className="career-readiness-card-label">Current term</div>
                        {currentTerm ? (
                          <div className="theme-card">
                            <div className="theme-header">
                              <span className="theme-name">{currentTerm.termLabel ?? 'Current term'}</span>
                              <span className="overview-stat-detail">{currentTerm.totalCredits} credits</span>
                            </div>
                            <ul className="degree-schedule-semester-courses">
                              {currentTerm.courses.map((course) => (
                                <li key={course.id} className="degree-schedule-semester-course">
                                  <div className="degree-schedule-course-row">
                                    <span>
                                      <strong>{course.course_code}</strong>
                                      {course.title && <small>{course.title}</small>}
                                    </span>
                                    <span>{course.credit_hours} credits</span>
                                  </div>
                                  <span className="degree-schedule-badge degree-schedule-badge--in-progress">In progress</span>
                                </li>
                              ))}
                            </ul>
                            <button
                              type="button"
                              className="overview-schedule-link"
                              onClick={() => navigateToAcademicSubTab('course-discovery')}
                            >
                              View full schedule →
                            </button>
                          </div>
                        ) : (
                          <p className="empty-state">No current term.</p>
                        )}
                      </div>
                    </div>
                  </section>
                  <section className="overview-block">
                    <div className="overview-block-title">Career readiness</div>
                    <p>{dashboard.career.confirmed ? `${String(dashboard.career.target_roles.length)} target roles and ${String(dashboard.career.skills.technical.length + dashboard.career.skills.soft.length)} skills confirmed.` : 'No confirmed career profile yet.'}</p>
                    {!dashboard.career.confirmed && <Link to="/resume" className="btn btn-primary btn-sm">Upload resume</Link>}
                    <div className="career-readiness-cards">
                      <div>
                        <div className="career-readiness-card-label">Top matched role</div>
                        {topRole ? (
                          <div className="theme-card">
                            <div className="theme-header">
                              <span className="theme-name">{topRole.role}</span>
                              <span className={`fit-badge fit-badge--${topRole.fit_level}`}>{FIT_LEVEL_LABEL[topRole.fit_level]}</span>
                            </div>
                          </div>
                        ) : (
                          <p className="empty-state">Not yet available — run Role Fit under Career.</p>
                        )}
                      </div>
                      <div>
                        <div className="career-readiness-card-label">Biggest skill gap</div>
                        {biggestGap ? (
                          <div className="theme-card">
                            <div className="theme-header">
                              <span className="theme-name">{biggestGap.gap}</span>
                              <span className={`gap-priority-badge gap-priority-badge--${biggestGap.priority}`}>
                                {biggestGap.priority === 'must' ? 'Must-Have' : 'Nice-to-Have'}
                              </span>
                            </div>
                          </div>
                        ) : (
                          <p className="empty-state">Not yet available — run Readiness Check under Career.</p>
                        )}
                      </div>
                    </div>
                  </section>
                </div>
              </div>
            )}

            {activeSection === 'academic' && academicSubTab === 'overview' && (
              <div className="stage-section">
                <h2 className="academic-section-heading">Academic Overview</h2>
                {!dashboard.courses.length ? (
                  <div className="real-empty"><h3>Add your academic history</h3><p>Upload and confirm your transcript to see courses and GPA here.</p><Link to="/transcript" className="btn btn-primary btn-sm">Upload transcript</Link></div>
                ) : (
                  <>
                    <div className="overview-stats">
                      <div className="overview-stat"><span className="overview-stat-value">{dashboard.officialGpa?.toFixed(2) ?? '—'}</span><span className="overview-stat-label">Official GPA</span></div>
                      <div className="overview-stat"><span className="overview-stat-value">{dashboard.projectedGpa?.toFixed(2) ?? '—'}</span><span className="overview-stat-label">Projected GPA</span></div>
                      <div className="overview-stat"><span className="overview-stat-value">{dashboard.earnedHours}</span><span className="overview-stat-label">Earned Hours</span></div>
                    </div>
                    {/* Same note as the GPA Calculator's, pointing there rather
                        than repeating its grade-entry controls on what is meant
                        to stay a simple snapshot. */}
                    <p className="gpa-projection-note">
                      {dashboard.inProgressWithCurrentGradeCount > 0
                        ? `Based on current grades in ${dashboard.inProgressWithCurrentGradeCount} in-progress course${dashboard.inProgressWithCurrentGradeCount === 1 ? '' : 's'}.`
                        : 'Enter current grades in GPA Calculator to see your projected GPA.'}
                    </p>
                    {/* "What does my academic situation look like right now" --
                        current (in-progress) coursework only, not the full term
                        planner. Planning and grade entry live one level down,
                        in GPA Calculator. */}
                    <section className="academic-overview-current">
                      <h3 className="term-courses-heading">Current coursework</h3>
                      {academicOverviewCurrentCourses.length === 0 ? (
                        <p className="empty-state">No in-progress coursework on record.</p>
                      ) : (
                        <>
                          {academicOverviewCurrentTermLabel && (
                            <p className="academic-overview-term-label">{academicOverviewCurrentTermLabel}</p>
                          )}
                          <div className="real-course-table" role="table" aria-label="Current coursework">
                            {academicOverviewCurrentCourses.map((course) => (
                              <div className="real-course-row" role="row" key={course.id}>
                                <span role="cell"><strong>{course.course_code}</strong><small>{course.title ?? 'Untitled course'}</small></span>
                                <span role="cell">{course.credit_hours} credits</span>
                                <span role="cell">{course.letter_grade ?? 'In progress'}</span>
                              </div>
                            ))}
                          </div>
                        </>
                      )}
                    </section>
                    {/* Compact reflection of the same run Course Discovery
                        itself shows (courseDiscoveryRun, lifted above) -- not
                        a second analysis or a second result store. */}
                    <section className="academic-overview-course-discovery">
                      <h3 className="term-courses-heading">Course Discovery</h3>
                      {courseDiscoverySuccess ? (
                        <>
                          <p className="academic-overview-cd-role">For: {courseDiscoverySuccess.target_role}</p>
                          <p className="academic-overview-cd-count">
                            {courseDiscoverySuccess.verified_recommendations.length} recommended course
                            {courseDiscoverySuccess.verified_recommendations.length === 1 ? '' : 's'}
                          </p>
                          {courseDiscoverySuccess.verified_recommendations.length > 0 && (
                            <ul className="academic-overview-cd-list">
                              {courseDiscoverySuccess.verified_recommendations.slice(0, 3).map((course) => (
                                <li key={`${course.institution}:${course.course_code}`}>
                                  <strong>{course.course_code}</strong> {course.title}
                                </li>
                              ))}
                            </ul>
                          )}
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            onClick={() => navigateToAcademicSubTab('course-discovery')}
                          >
                            View Course Discovery →
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() => navigateToAcademicSubTab('course-discovery')}
                        >
                          Discover courses that support your career goals →
                        </button>
                      )}
                    </section>
                    <section className="academic-overview-grade-calculator">
                      <h3 className="term-courses-heading">Grade Calculator</h3>
                      <p className="empty-state">See what you need to reach your target grade in each course.</p>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => navigateToAcademicSubTab('grade-calculator')}
                      >
                        Open Grade Calculator →
                      </button>
                    </section>
                    <p className="academic-overview-status">
                      Academic status: {dashboard.completeness.academics.ready_for_academic_features ? 'Ready' : 'Incomplete'}
                    </p>
                  </>
                )}
              </div>
            )}

            {activeSection === 'academic' && academicSubTab === 'gpa-calculator' && (
              <div className="stage-section">
                <h2 className="academic-section-heading">GPA Calculator</h2>
                {!dashboard.courses.length ? (
                  <div className="real-empty"><h3>Add your academic history</h3><p>Upload and confirm your transcript to see courses and GPA here.</p><Link to="/transcript" className="btn btn-primary btn-sm">Upload transcript</Link></div>
                ) : (
                  <>
                    <div className="overview-stats">
                      <div className="overview-stat"><span className="overview-stat-value">{dashboard.officialGpa?.toFixed(2) ?? '—'}</span><span className="overview-stat-label">Official GPA</span></div>
                      <div className="overview-stat"><span className="overview-stat-value">{dashboard.projectedGpa?.toFixed(2) ?? '—'}</span><span className="overview-stat-label">Projected GPA</span></div>
                      <div className="overview-stat"><span className="overview-stat-value">{dashboard.earnedHours}</span><span className="overview-stat-label">Earned Hours</span></div>
                    </div>
                    {/* Projected GPA only differs from Official once a current
                        grade has been entered on an in-progress course -- see
                        gpa.py's official/projected scopes. This line explains
                        the gap (or its absence) rather than leaving the two
                        numbers to speak for themselves. */}
                    <p className="gpa-projection-note">
                      {dashboard.inProgressWithCurrentGradeCount > 0
                        ? `Based on current grades in ${dashboard.inProgressWithCurrentGradeCount} in-progress course${dashboard.inProgressWithCurrentGradeCount === 1 ? '' : 's'}.`
                        : 'Enter current grades to see your projected GPA.'}
                    </p>
                    {/* The flat all-courses list is replaced by the term view:
                        one term at a time, chosen from a dropdown that opens on
                        the upcoming term. The GPA/hours stats above stay
                        cumulative and unfiltered -- they are the whole record,
                        and scoping them to one term would quietly change what
                        "Official GPA" means. */}
                    {accessToken
                      ? (
                        <TermPlanner
                          slug={null}
                          accessToken={accessToken}
                          courses={dashboard.courses}
                          onCourseRecordsChanged={() => { void reloadStudentProfile(); }}
                        />
                      )
                      : (
                        <div className="real-course-table" role="table" aria-label="Confirmed courses">
                          {dashboard.courses.map((course) => (
                            <div className="real-course-row" role="row" key={course.id}>
                              <span role="cell"><strong>{course.course_code}</strong><small>{course.title ?? 'Untitled course'}</small></span>
                              <span role="cell">{course.credit_hours} credits</span>
                              <span role="cell">{course.letter_grade ?? 'In progress'}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    {dashboard.repeatExclusions.length > 0 && <p className="real-note">{dashboard.repeatExclusions.length} course attempt(s) excluded from GPA by the institution repeat policy.</p>}
                  </>
                )}
              </div>
            )}

            {activeSection === 'academic' && academicSubTab === 'grade-calculator' && (
              <div className="stage-section">
                <GradeCalculatorPanel
                  accessToken={accessToken}
                  courses={dashboard.courses}
                  institutionName={dashboard.institutionName}
                />
              </div>
            )}

            {activeSection === 'academic' && academicSubTab === 'course-discovery' && (
              <div className="stage-section">
                {/* CourseDiscoveryPanel renders its own "Course Discovery"
                    heading (via AnalysisPanel's title), so no page-level
                    heading is added here -- that would just duplicate it. */}
                <CourseDiscoveryPanel
                  targetRoles={dashboard.career.target_roles}
                  run={courseDiscoveryRun}
                  selectedRole={courseDiscoverySelectedRole}
                  onSelectedRoleChange={setCourseDiscoverySelectedRole}
                />
                <div className="degree-planner-flow">
                  <DegreePlannerSummary
                    institution={dashboard.institutionName}
                    major={major}
                    expectedGraduation={dashboard.expectedGraduation}
                    schedule={degreeScheduleResult}
                  />
                  <DegreeSchedulePanel
                    targetRole={dashboard.career.target_roles[0]}
                    courses={dashboard.courses}
                    onResult={setDegreeScheduleResult}
                  />
                  <RequirementSatisfactionPanel />
                </div>
              </div>
            )}

            {activeSection === 'career' && careerSubTab === 'overview' && (
              <div className="stage-section">
                {!dashboard.career.confirmed ? (
                  <>
                    <h2 className="career-section-heading">Career Profile</h2>
                    <div className="real-empty"><h3>Build your career profile</h3><p>Upload and confirm your resume before career facts appear here.</p><Link to="/resume" className="btn btn-primary btn-sm">Upload resume</Link></div>
                  </>
                ) : (
                  <>
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
                  </>
                )}
              </div>
            )}

            {activeSection === 'career' && careerSubTab === 'intelligence' && (
              <div className="stage-section career-subtab-panel career-intelligence">
                <h2 className="career-section-heading">Career Intelligence</h2>
                <p className="career-intelligence-role">Target role: <strong>{dashboard.career.target_roles[0] ?? 'Not provided'}</strong></p>
                <section className="career-intelligence-section"><FitAnalysisPanel run={fitRun} /></section>
                <section className="career-intelligence-section"><GapAnalysisPanel run={gapRun} /></section>
                <section className="career-intelligence-section"><ShiftAnalysisPanel run={shiftRun} /></section>
              </div>
            )}

            {activeSection === 'career' && careerSubTab === 'job-search' && (
              <div className="stage-section">
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
              <div className="stage-section career-subtab-panel">
                {!dashboard.career.confirmed ? (
                  <><h2 className="career-section-heading">Career Profile</h2><div className="real-empty"><h3>Build your career profile</h3><p>Upload and confirm your resume before career facts appear here.</p><Link to="/resume" className="btn btn-primary btn-sm">Upload resume</Link></div></>
                ) : (
                      <>
                      <ProfileChecklist
                        missing={missingDetails}
                        onJump={(field, trigger) => { requestField({ path: field.path, trigger }); }}
                      />
                      <div className="career-profile-block">
                        <h2 className="career-section-heading">Career Profile</h2>
                        {/* Graduation and the majors are academic record, not
                            career record, so they arrive as props rather than
                            being dug out of the profile by the career component.
                            All three were already on the view model and simply
                            unread -- nothing new is fetched to render them. */}
                        <CareerProfile
                          career={dashboard.career}
                          details={{
                            expectedGraduation: dashboard.expectedGraduation,
                            majorCurrent: dashboard.majorCurrent,
                            majorIntended: dashboard.majorIntended,
                          }}
                          // Each field PATCHes only its own keys and then
                          // reloads, so the page re-renders from the server's
                          // answer rather than from what the editor hoped it
                          // wrote. Without a token there is nothing to save
                          // with, so the profile stays read-only rather than
                          // growing buttons that cannot work.
                          editing={
                            accessToken
                              ? {
                                  persist: async (changes) => { await updateProfile(accessToken, changes); },
                                  onSaved: async () => {
                                    await reloadStudentProfile();
                                    setProfileSaved(true);
                                  },
                                }
                              : null
                          }
                          focus={fieldFocus}
                        />
                      </div>
                      </>
                )}
              </div>
            )}
          </div>
        </main>
      </div>
      {profileSaved && <div className="profile-save-notice" role="status">Profile saved. Your guidance now uses the latest details.<button type="button" aria-label="Dismiss profile saved message" onClick={() => setProfileSaved(false)}>×</button></div>}
    </div></ProfileCompletionContext.Provider>
  );
}
