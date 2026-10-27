import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { analyzeCourseDiscovery, analyzeFit, analyzeGap, analyzeShift } from '../api/analysis';
import { useAnalysisRun } from '../hooks/useAnalysisRun';
import { useCachedAnalysisRun } from '../hooks/useCachedAnalysisRun';
import { useCanvasCalendar } from '../hooks/useCanvasCalendar';
import { useSequencedAnalysisRuns } from '../hooks/useSequencedAnalysisRuns';
import { ChatPanel } from '../components/ChatPanel';
import { ErrorBoundary } from '../components/ErrorBoundary';
import { useFocusTrap } from '../hooks/useFocusTrap';
import { useUrlParams } from '../hooks/useUrlParams';
import { GuidedTour } from '../components/GuidedTour';
import { ReportIssueButton } from '../components/ReportIssueButton';
import { MemoryNotesPanel } from '../components/career/MemoryNotesPanel';
import { supabase } from '../lib/supabase';
import {
  TOUR_COMPLETED_METADATA_KEY,
  needsAccountBackfill,
  shouldAutoOpenTour,
  tourCompletedOnAccount,
  tourSeenStorageKey,
} from '../lib/onboardingTour.mjs';
import { DashboardSuccessNotice } from '../components/DashboardSuccessNotice';
import { CourseDiscoveryPanel } from '../components/CourseDiscoveryPanel';
import { RequirementSatisfactionPanel } from '../components/RequirementSatisfactionPanel';
import { DegreeProgressRing } from '../components/DegreeProgressRing';
import { RequirementCelebration, useRequirementCelebration } from '../components/RequirementCelebration';
import { EmptyState } from '../components/EmptyState';
import { StatusStat } from '../components/StatusStat';
import { fetchRequirementSatisfaction, isSkippedRequirementSatisfaction } from '../api/requirementSatisfaction.mjs';
import { countSatisfiedLeafGroups } from '../lib/requirementProgress.mjs';
import { pickTopRole, pickBiggestGap } from '../lib/careerReadinessCards.mjs';
import { currentTermSnapshot } from '../lib/currentTermSnapshot.mjs';
import { DegreeSchedulePanel } from '../components/DegreeSchedulePanel';
import { DegreePlannerSummary } from '../components/DegreePlannerSummary';
import type { DegreeScheduleResponse } from '../api/degreeSchedule.mjs';
import { FitAnalysisPanel, FIT_LEVEL_LABEL } from '../components/FitAnalysisPanel';
import { JobSearchPanel } from '../components/JobSearchPanel';
import { GapAnalysisPanel } from '../components/GapAnalysisPanel';
import { ShiftAnalysisPanel } from '../components/ShiftAnalysisPanel';
import { TermPlanner } from '../components/TermPlanner';
import { CanvasCalendarPanel } from '../components/CanvasCalendarPanel';
import { NextDueAlert } from '../components/NextDueAlert';
import { scrollWhenThere } from '../chat/useChatAction';
import { CHAT_ACTIONS } from '../lib/chatActions.mjs';
import { GradeCalculatorPanel } from '../components/GradeCalculatorPanel';
import { CareerProfile, type CareerFieldFocus } from '../components/career/CareerProfile';
import { updateProfile } from '../api/profile';
import { ProfileChecklist } from '../components/career/ProfileChecklist';
import { ProfileCompletionContext, type ProfileFieldRequest } from '../components/profile/ProfileCompletionContext';
import { AnimatedNumber } from '../components/AnimatedNumber';
import { formatFixed } from '../lib/format.mjs';
import { GpaSparkline, GpaTrendChart } from '../components/GpaTrendChart';
import { countLabel } from '../lib/countLabel.mjs';
import { buildDashboardViewModel } from '../data/dashboardViewModel';
import { missingChecklistFields } from '../lib/profileChecklist';

type NavSection = 'overview' | 'academic' | 'career';

const NAV_ITEMS: Array<{ key: NavSection; label: string }> = [
  { key: 'overview', label: 'Overview' },
  { key: 'academic', label: 'Academic' },
  { key: 'career', label: 'Career' },
];

// Mirrors NavSection -- kept as its own list (rather than mapped from
// NAV_ITEMS) so it reads as plain data for useUrlParams' allowedValues,
// with no dependency on NAV_ITEMS' shape.
const SECTION_VALUES: NavSection[] = ['overview', 'academic', 'career'];

type CareerSubTab = 'overview' | 'intelligence' | 'job-search' | 'profile';
type IntelligencePanel = 'fit' | 'gap' | 'shift';

const CAREER_SUB_TABS: Array<{ key: CareerSubTab; label: string }> = [
  { key: 'intelligence', label: 'Career Intelligence' },
  { key: 'job-search', label: 'Job Search' },
  { key: 'profile', label: 'Career Profile' },
];

// Unlike CAREER_SUB_TABS (the visible nav list), this includes 'overview' --
// the implicit default state a URL param can validly hold.
const CAREER_SUB_TAB_VALUES: CareerSubTab[] = ['overview', 'intelligence', 'job-search', 'profile'];

// 'overview' is Academic's own default view -- what the top-level Academic
// nav item itself renders -- not a visible child tab. Only these two appear
// as nested nav items under Academic.
type AcademicSubTab = 'overview' | 'gpa-calculator' | 'grade-calculator' | 'course-discovery';

const ACADEMIC_SUB_TABS: Array<{ key: AcademicSubTab; label: string }> = [
  { key: 'gpa-calculator', label: 'GPA Calculator' },
  { key: 'grade-calculator', label: 'Grade Calculator' },
  { key: 'course-discovery', label: 'Course Discovery' },
];

const ACADEMIC_SUB_TAB_VALUES: AcademicSubTab[] = [
  'overview',
  'gpa-calculator',
  'grade-calculator',
  'course-discovery',
];

// localStorage can throw (blocked storage, some private modes); the tour flag
// is a convenience, so a failure just reads as "not seen in this browser".
function readTourSeenInBrowser(userId: string): boolean {
  try {
    return localStorage.getItem(tourSeenStorageKey(userId)) === '1';
  } catch {
    return false;
  }
}

function writeTourSeenInBrowser(userId: string) {
  try {
    localStorage.setItem(tourSeenStorageKey(userId), '1');
  } catch {
    // Account metadata below is the durable copy.
  }
}

export function AuthenticatedDashboard() {
  const { studentAccount, signOutSession, session, slug, reloadStudentProfile } = useAuth();
  // First-run tour: auto-shows once per account (see onboardingTour.mjs for
  // why completion lives in user_metadata), and the "?" button replays it.
  const tourUserId = session?.user?.id ?? null;
  const tourUserMetadata = session?.user?.user_metadata;
  const [tourOpen, setTourOpen] = useState<boolean>(() =>
    tourUserId
      ? shouldAutoOpenTour({ userMetadata: tourUserMetadata, seenInBrowser: readTourSeenInBrowser(tourUserId) })
      : false,
  );
  // Best effort: a failed write leaves the browser copy in place, and the next
  // close or sign-in tries again.
  const recordTourCompletedOnAccount = useCallback(async () => {
    const { error } = await supabase.auth.updateUser({
      data: { [TOUR_COMPLETED_METADATA_KEY]: new Date().toISOString() },
    });
    if (error) console.warn('[AuthenticatedDashboard] could not save tour completion:', error.message);
  }, []);
  // Someone who finished the tour in this browser before completion moved to
  // the account gets it copied up once, so other browsers stop showing it too.
  // The ref keeps StrictMode's doubled effect from writing twice.
  const tourBackfilledFor = useRef<string | null>(null);
  useEffect(() => {
    if (!tourUserId || tourBackfilledFor.current === tourUserId) return;
    tourBackfilledFor.current = tourUserId;
    if (needsAccountBackfill({ userMetadata: tourUserMetadata, seenInBrowser: readTourSeenInBrowser(tourUserId) })) {
      void recordTourCompletedOnAccount();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per signed-in user
  }, [tourUserId]);
  // The term view reads planned_courses and the catalog through the session
  // bearer token. Absent one, the section falls back to the flat course list
  // below rather than rendering an empty planner.
  const accessToken = session?.access_token ?? null;
  const navigate = useNavigate();
  // Backed by the URL (see useUrlParams) rather than useState, so the
  // current section/tab survives a refresh and can be shared as a link.
  // All three read from one shared getParam/setParams pair -- see
  // useUrlParams' doc comment for why that sharing matters whenever a
  // handler below changes more than one of these at once.
  const { getParam, setParams } = useUrlParams();
  // The 404 page's "Ask GradusIQ" lands here with { ask: true } in router
  // state: focus the chat once, then let go so coming back to Overview later
  // doesn't grab focus again.
  const location = useLocation();
  const [askOnArrival, setAskOnArrival] = useState(() => (location.state as { ask?: unknown } | null)?.ask === true);
  useEffect(() => {
    if (askOnArrival) setAskOnArrival(false);
  }, [askOnArrival]);
  const activeSection = getParam('section', 'overview', SECTION_VALUES);
  const careerSubTab = getParam('career', 'overview', CAREER_SUB_TAB_VALUES);
  const academicSubTab = getParam('academic', 'overview', ACADEMIC_SUB_TAB_VALUES);
  // Single-key version for callers (GuidedTour) that only ever switch the
  // top-level section and, like the old useState setter, don't touch either
  // sub-tab.
  const setActiveSection = useCallback(
    (section: NavSection) => setParams({ section: section === 'overview' ? null : section }),
    [setParams],
  );
  const [railOpen, setRailOpen] = useState(false);
  const railRef = useRef<HTMLElement>(null);
  const railTriggerRef = useRef<HTMLButtonElement>(null);

  // Mobile nav rail: a drawer below 768px (see index.css's mobile media
  // query), an ordinary always-visible sidebar above it. The overlay click
  // already closed it; keyboard users had no way to, since nothing handled
  // Escape and Tab could walk straight past the rail's own last button into
  // the (visually hidden-behind-the-scrim) main content.
  const closeRail = useCallback(() => {
    setRailOpen(false);
    railTriggerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (railOpen) railRef.current?.focus();
  }, [railOpen]);

  useEffect(() => {
    if (!railOpen) return undefined;
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') closeRail();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [railOpen, closeRail]);

  // Only traps Tab while the rail is actually acting as a drawer (open, at
  // mobile widths) -- see useFocusTrap's own note on why `active` matters
  // for an always-mounted element like this one.
  useFocusTrap(railRef, railOpen);

  // Profile disclosure on the identity block (initials + name), the place
  // students expect to find their profile. A plain disclosure, not an ARIA
  // menu: the trigger reports aria-expanded and the panel is a list of links
  // and buttons in the normal Tab order. Closes on Escape (focus returns to the
  // trigger) or a click outside it.
  const [profileMenuOpen, setProfileMenuOpen] = useState(false);
  const profileMenuRef = useRef<HTMLDivElement>(null);
  const profileTriggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!profileMenuOpen) return undefined;
    function onPointer(event: PointerEvent) {
      if (!profileMenuRef.current?.contains(event.target as Node)) setProfileMenuOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.stopPropagation();
        setProfileMenuOpen(false);
        profileTriggerRef.current?.focus();
      }
    }
    document.addEventListener('pointerdown', onPointer);
    window.addEventListener('keydown', onKey, true);
    return () => {
      document.removeEventListener('pointerdown', onPointer);
      window.removeEventListener('keydown', onKey, true);
    };
  }, [profileMenuOpen]);

  const [fieldFocus, setFieldFocus] = useState<CareerFieldFocus | null>(null);
  const [profileSaved, setProfileSaved] = useState(false);
  const [degreeScheduleResult, setDegreeScheduleResult] = useState<DegreeScheduleResponse | null>(null);
  // Lifted out of GapAnalysisPanel/FitAnalysisPanel/ShiftAnalysisPanel (each
  // still owns its own internal useCachedAnalysisRun by default) so Career
  // Overview and Career Intelligence read the same independent run states.
  // useCachedAnalysisRun keeps the existing cache behavior for each feature.
  const rawGapRun = useCachedAnalysisRun('gap', () => analyzeGap({ slug, accessToken }));
  const rawFitRun = useCachedAnalysisRun('fit', () => analyzeFit({ slug, accessToken }));
  const rawShiftRun = useCachedAnalysisRun('shift', () => analyzeShift({ slug, accessToken }));
  // Gated to one live call at a time -- see useSequencedAnalysisRuns.
  const { fit: fitRun, gap: gapRun, shift: shiftRun } = useSequencedAnalysisRuns({
    fit: rawFitRun,
    gap: rawGapRun,
    shift: rawShiftRun,
  });
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
  // One Canvas calendar request per session, shared by the Academic card and
  // the Overview's next-due alert. Skipped for demo identities (no token) and
  // for students with no confirmed courses, who are not shown the card.
  const canvasCalendar = useCanvasCalendar(accessToken, (dashboard?.courses.length ?? 0) > 0);
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
  const requestField = useCallback(
    (request: ProfileFieldRequest) => {
      // The field only renders inside CareerProfile, which now lives on the
      // Career Profile child rather than directly on the Career overview —
      // so a skipped-analysis "Add this" link has to land the student there
      // too, not just on whichever Career sub-tab happened to be open. Both
      // params change together, so this goes through setParams once rather
      // than two separate setters -- see useUrlParams' doc comment.
      setParams({ section: 'career', career: 'profile' });
      setRailOpen(false);
      // A new object every time, so asking twice for the same field works.
      setFieldFocus({ path: request.path, nonce: Date.now() });
    },
    [setParams],
  );

  // GAP/FIT/SHIFT summaries on Overview and Career Overview link straight to
  // their own panel on Career Intelligence, not just the top of that tab.
  const [intelligenceTarget, setIntelligenceTarget] = useState<IntelligencePanel | null>(null);

  useEffect(() => {
    if (!intelligenceTarget || activeSection !== 'career' || careerSubTab !== 'intelligence') return;
    document.getElementById(`career-intelligence-${intelligenceTarget}`)?.scrollIntoView({ block: 'start' });
    setIntelligenceTarget(null);
  }, [intelligenceTarget, activeSection, careerSubTab]);

  // 'skipped' (no program to evaluate against yet) collapses to the same
  // { satisfied: 0, total: 0 } as 'loading'/'transport-error' -- the ring
  // renders its dash for all three, since none of them is a real 0-of-0.
  const requirementGroups =
    requirementRun.state.phase === 'done' && !isSkippedRequirementSatisfaction(requirementRun.state.result)
      ? requirementRun.state.result.groups
      : [];
  const degreeProgress = countSatisfiedLeafGroups(requirementGroups);
  const celebration = useRequirementCelebration({
    studentId: studentAccount.profile?.student.id ?? null,
    groups: requirementGroups,
    ready: requirementRun.state.phase === 'done' && !isSkippedRequirementSatisfaction(requirementRun.state.result),
    active: activeSection === 'overview',
    progress: degreeProgress,
  });

  if (!dashboard) return null;

  const displayName = dashboard.name ?? 'Student';
  const major = dashboard.majorCurrent ?? dashboard.majorIntended;
  const readiness = dashboard.completeness.overall;


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
    // The top-level Academic/Career item IS each one's own overview --
    // clicking it, whether arriving fresh or returning from a child, always
    // resets to it rather than leaving whichever child was last open. Both
    // params change together, so one setParams call, not two setters.
    setParams({
      section: section === 'overview' ? null : section,
      ...(section === 'academic' ? { academic: null } : {}),
      ...(section === 'career' ? { career: null } : {}),
    });
    setRailOpen(false);
  }

  function navigateToAcademicSubTab(tab: AcademicSubTab) {
    setParams({ section: 'academic', academic: tab === 'overview' ? null : tab });
    setRailOpen(false);
  }

  function navigateToCareerSubTab(tab: CareerSubTab) {
    setParams({ section: 'career', career: tab === 'overview' ? null : tab });
    setRailOpen(false);
  }

  // The overview's next-due alert: same destination and scroll target as the
  // assistant's "Connect Canvas calendar" action, without opening the chat.
  function openCanvasCard() {
    navigateToAcademicSubTab('overview');
    const target = CHAT_ACTIONS['canvas-calendar'].scrollTo;
    if (target) scrollWhenThere(target);
  }

  function openIntelligencePanel(panel: IntelligencePanel) {
    navigateToCareerSubTab('intelligence');
    setIntelligenceTarget(panel);
  }

  // Finishing, skipping, Escape and the end CTAs all count as done.
  function handleTourClose() {
    setTourOpen(false);
    if (!tourUserId) return;
    writeTourSeenInBrowser(tourUserId);
    if (!tourCompletedOnAccount(tourUserMetadata)) void recordTourCompletedOnAccount();
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
      {railOpen && <div className="rail-overlay" onClick={closeRail} aria-hidden="true" />}
      <aside ref={railRef} tabIndex={-1} className={`rail${railOpen ? ' rail--open' : ''}`} aria-label="Dashboard navigation">
        <div className="rail-brand">
          <span className="rail-brand-mark" aria-hidden="true" />
          <span className="rail-brand-name" translate="no">GradusIQ</span>
        </div>
        <div className="rail-identity" ref={profileMenuRef}>
          <button
            ref={profileTriggerRef}
            type="button"
            className="rail-identity-button"
            onClick={() => setProfileMenuOpen((open) => !open)}
            aria-expanded={profileMenuOpen}
            aria-controls="rail-profile-menu"
          >
            <span className="rail-monogram" aria-hidden="true">{dashboard.initials || 'ST'}</span>
            <span className="rail-name">{displayName}</span>
            <svg className="rail-identity-caret" aria-hidden="true" viewBox="0 0 12 8" width="10" height="7" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M1 1.5l5 5 5-5" />
            </svg>
          </button>
          {profileMenuOpen && (
            <ul id="rail-profile-menu" className="rail-profile-menu" aria-label="Profile">
              <li><button type="button" onClick={() => { setProfileMenuOpen(false); navigateToCareerSubTab('profile'); }}>Career Profile</button></li>
              <li><Link to="/transcript" onClick={() => setProfileMenuOpen(false)}>Update transcript</Link></li>
              <li><Link to="/resume" onClick={() => setProfileMenuOpen(false)}>Update resume</Link></li>
              <li><button type="button" onClick={() => { setProfileMenuOpen(false); void handleLogout(); }}>Log out</button></li>
            </ul>
          )}
          <div className="rail-meta">
            <span>{dashboard.classification ?? 'Student'}</span>
            <span className="rail-dot" aria-hidden="true">·</span>
            <span className="rail-gpa">{dashboard.officialGpa !== null ? formatFixed(dashboard.officialGpa, 2) : '—'}</span>
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
          <button ref={railTriggerRef} type="button" className="topbar-menu" onClick={() => setRailOpen(true)} aria-label="Open navigation" aria-expanded={railOpen}>
            <span className="topbar-menu-icon" aria-hidden="true"><span /></span>
          </button>
          <h2 className="topbar-title">{NAV_ITEMS.find((item) => item.key === activeSection)?.label}</h2>
          <ReportIssueButton
            accessToken={accessToken}
            defaultName={studentAccount.profile?.student.name ?? ''}
            defaultEmail={session?.user?.email ?? ''}
            pageLabel={NAV_ITEMS.find((item) => item.key === activeSection)?.label ?? 'Dashboard'}
          />
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
              <div className="stage-section overview-page">
                <div className="overview-header">
                  <h1 className="overview-name">{displayName}</h1>
                  <div className="overview-vitals">
                    <span>{major ?? 'Major not provided'}</span>
                    <span className="overview-vitals-sep" aria-hidden="true">·</span>
                    <span>{dashboard.institutionName ?? 'Institution not provided'}</span>
                  </div>
                </div>
                <NextDueAlert
                  result={canvasCalendar.state}
                  enabled={accessToken !== null && dashboard.courses.length > 0}
                  onOpen={openCanvasCard}
                />
                <ChatPanel autoFocus={askOnArrival} />
                <div className="overview-stats">
                  <div className="overview-stat"><span className="overview-stat-value"><AnimatedNumber value={dashboard.officialGpa} decimals={2} countIn /></span><span className="overview-stat-label">Official GPA</span><GpaSparkline points={dashboard.gpaByTerm} onOpen={() => navigateToAcademicSubTab('gpa-calculator')} /></div>
                  <div className="overview-stat"><span className="overview-stat-value"><AnimatedNumber value={dashboard.courses.length} decimals={0} countIn /></span><span className="overview-stat-label">Confirmed Courses</span></div>
                  <StatusStat label="Profile Status" tone={readiness}>{readiness}</StatusStat>
                  <DegreeProgressRing satisfied={degreeProgress.satisfied} total={degreeProgress.total} celebrate={celebration.message !== null} />
                </div>
                {/* Under the tiles, not above them: the requirements arrive after the
                    page has drawn, and a line appearing here pushes down the
                    readiness cards instead of the stat row whose ring is bursting. */}
                <RequirementCelebration message={celebration.message} onDismiss={celebration.dismiss} />
                <div className="overview-grid">
                  <section className="overview-block">
                    <div className="overview-block-title">Academic readiness</div>
                    <p>{dashboard.completeness.academics.transcript_data_present ? `${countLabel(dashboard.courses.length, 'confirmed course')} across ${countLabel(dashboard.terms.length, 'term')}.` : 'No confirmed transcript data yet.'}</p>
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
                              View Full Schedule →
                            </button>
                          </div>
                        ) : (
                          <EmptyState
                            icon="calendar"
                            action={<button type="button" className="btn btn-ghost btn-sm" onClick={() => navigateToAcademicSubTab('course-discovery')}>Plan your schedule</button>}
                          >
                            No current term.
                          </EmptyState>
                        )}
                      </div>
                    </div>
                  </section>
                  <section className="overview-block">
                    <div className="overview-block-title">Career readiness</div>
                    <p>{dashboard.career.confirmed ? `${countLabel(dashboard.career.target_roles.length, 'target role')} and ${countLabel(dashboard.career.skills.technical.length + dashboard.career.skills.soft.length, 'skill')} confirmed.` : 'No confirmed career profile yet.'}</p>
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
                            <button type="button" className="btn btn-ghost btn-sm career-readiness-link" onClick={() => openIntelligencePanel('fit')}>See Role Fit</button>
                          </div>
                        ) : (
                          <EmptyState
                            icon="target"
                            action={<button type="button" className="btn btn-ghost btn-sm" onClick={() => openIntelligencePanel('fit')}>Open Role Fit</button>}
                          >
                            No role match yet.
                          </EmptyState>
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
                            <button type="button" className="btn btn-ghost btn-sm career-readiness-link" onClick={() => openIntelligencePanel('gap')}>See all skill gaps</button>
                          </div>
                        ) : (
                          <EmptyState
                            icon="bars"
                            action={<button type="button" className="btn btn-ghost btn-sm" onClick={() => openIntelligencePanel('gap')}>Open Readiness Check</button>}
                          >
                            No readiness check yet.
                          </EmptyState>
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
                      <div className="overview-stat"><span className="overview-stat-value">{dashboard.officialGpa !== null ? formatFixed(dashboard.officialGpa, 2) : '—'}</span><span className="overview-stat-label">Official GPA</span></div>
                      <div className="overview-stat"><span className="overview-stat-value"><AnimatedNumber value={dashboard.projectedGpa} decimals={2} showDelta /></span><span className="overview-stat-label">Projected GPA</span></div>
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
                        <EmptyState
                          icon="calendar"
                          action={<button type="button" className="btn btn-ghost btn-sm" onClick={() => navigateToAcademicSubTab('gpa-calculator')}>Plan this term</button>}
                        >
                          No in-progress coursework on record.
                        </EmptyState>
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
                                <span role="cell">
                                  {course.letter_grade ?? <span className="degree-schedule-badge degree-schedule-badge--in-progress">In progress</span>}
                                </span>
                              </div>
                            ))}
                          </div>
                        </>
                      )}
                    </section>
                    {/* Due dates and exams from the student's Canvas calendar
                        feed. Session-only: a demo identity has no feed. */}
                    {accessToken && <CanvasCalendarPanel accessToken={accessToken} calendar={canvasCalendar} />}
                    {/* Compact reflection of the same run Course Discovery
                        itself shows (courseDiscoveryRun, lifted above) -- not
                        a second analysis or a second result store. */}
                    <div className="academic-overview-shortcuts">
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
                          <>
                            <p className="academic-overview-shortcut-copy">Find courses at your school that build toward the roles you want.</p>
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm"
                              onClick={() => navigateToAcademicSubTab('course-discovery')}
                            >
                              Discover courses that support your career goals →
                            </button>
                          </>
                        )}
                      </section>
                      <section className="academic-overview-grade-calculator">
                        <h3 className="term-courses-heading">Grade Calculator</h3>
                        <p className="academic-overview-shortcut-copy">See what you need to reach your target grade in each course.</p>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() => navigateToAcademicSubTab('grade-calculator')}
                        >
                          Open Grade Calculator →
                        </button>
                      </section>
                    </div>
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
                      <div className="overview-stat"><span className="overview-stat-value">{dashboard.officialGpa !== null ? formatFixed(dashboard.officialGpa, 2) : '—'}</span><span className="overview-stat-label">Official GPA</span></div>
                      <div className="overview-stat"><span className="overview-stat-value"><AnimatedNumber value={dashboard.projectedGpa} decimals={2} showDelta /></span><span className="overview-stat-label">Projected GPA</span></div>
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
                    <GpaTrendChart points={dashboard.gpaByTerm} onSelectTerm={(termKey) => setParams({ term: termKey })} />
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
                {/* The page title every Academic sub-tab has; the panel's
                    own card title names what it holds ("Courses for your
                    target role") so the two don't repeat each other. */}
                <h2 className="academic-section-heading">Course Discovery</h2>
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
                        ['Role Fit', 'fit', fitRun.state],
                        ['Readiness', 'gap', gapRun.state],
                        ['Trend Guidance', 'shift', shiftRun.state],
                      ] as const).map(([label, panel, state]) => (
                        <section className="career-overview-summary" key={label}>
                          <h3>{label}</h3>
                          <p>{state.phase === 'done' ? state.result.summary : state.phase === 'loading' ? 'Analysis in progress.' : state.phase === 'transport-error' ? 'Analysis unavailable.' : 'No analysis has been run yet.'}</p>
                          <button type="button" className="btn btn-ghost btn-sm career-overview-summary-link" onClick={() => openIntelligencePanel(panel)} aria-label={`View ${label} details`}>View details</button>
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
                <section id="career-intelligence-fit" className="career-intelligence-section"><ErrorBoundary><FitAnalysisPanel run={fitRun} /></ErrorBoundary></section>
                <section id="career-intelligence-gap" className="career-intelligence-section"><ErrorBoundary><GapAnalysisPanel run={gapRun} /></ErrorBoundary></section>
                <section id="career-intelligence-shift" className="career-intelligence-section"><ErrorBoundary><ShiftAnalysisPanel run={shiftRun} /></ErrorBoundary></section>
              </div>
            )}

            {activeSection === 'career' && careerSubTab === 'job-search' && (
              <div className="stage-section">
                <h2 className="career-section-heading">Job Search</h2>
                <JobSearchPanel targetRoles={dashboard.career.target_roles} accessToken={accessToken} />
              </div>
            )}

            {activeSection === 'career' && careerSubTab === 'profile' && (
              <div className="stage-section career-subtab-panel">
                {!dashboard.career.confirmed ? (
                  <><h2 className="career-section-heading">Career Profile</h2><div className="real-empty"><h3>Build your career profile</h3><p>Upload and confirm your resume before career facts appear here.</p><Link to="/resume" className="btn btn-primary btn-sm">Upload resume</Link></div></>
                ) : (
                      <>
                      <h2 className="career-section-heading">Career Profile</h2>
                      <ProfileChecklist
                        missing={missingDetails}
                        onJump={(field, trigger) => { requestField({ path: field.path, trigger }); }}
                      />
                      <div className="career-profile-block">
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
                {/* Notes saved from the assistant chat; shown whether or not
                    the resume is confirmed, since chat works either way. */}
                {accessToken && (
                  <div className="career-profile-block">
                    <MemoryNotesPanel accessToken={accessToken} />
                  </div>
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
