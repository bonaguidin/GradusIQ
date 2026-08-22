import { useEffect, useMemo, useState } from 'react';
import { useAuth } from '../auth/useAuth';
import { analyzeActionPlan, analyzeCourseDiscovery, type AnalysisIdentity } from '../api/analysis';
import { analysisFailureMessage, useAnalysisRun, type AnalysisRunState } from '../hooks/useAnalysisRun';
import { useSupportedTargetRoles } from '../hooks/useSupportedTargetRoles';
import type {
  CourseDiscoveryData,
  FeatureResult,
  VerifiedCourseRecommendation,
  PrerequisiteBlockedCourse,
  UnresolvedCourseCandidate,
  PrerequisiteEvaluation,
  CareerSkillNeed,
  ActionPlanPreviewResponse,
  UnifiedActionPlan,
  DependencyOrderResult,
  DependencyOrderLimitation,
} from '../types/analysis';
import { AnalysisPanel, type AnalysisPhase } from './AnalysisPanel';

export interface CourseDiscoveryRun {
  state: AnalysisRunState<FeatureResult<CourseDiscoveryData>>;
  trigger: () => void;
}

interface CourseDiscoveryPanelProps {
  targetRoles: string[];
  /**
   * Lets a parent (Academic Overview's compact summary) read this exact run
   * instead of holding a second one -- so the summary always reflects the
   * same result this panel shows, with no duplicate fetch. Same pattern as
   * GapAnalysisPanel's externally-shared run. Omitted by every other caller,
   * which keeps its own internal useAnalysisRun instance exactly as before.
   */
  run?: CourseDiscoveryRun;
  /** Paired with `run`: the role that run's next trigger will request. */
  selectedRole?: string;
  onSelectedRoleChange?: (role: string) => void;
}

// Course Discovery panel — data shape is course_discovery/agent_models.py's
// CourseDiscoveryResult, mirrored in ../types/analysis.ts. Three typed
// outcomes (verified_recommendations, prerequisite_blocked,
// requires_verification), rendered as three visually distinct registers —
// see the file header comment in index.css's COURSE DISCOVERY block.
//
// Also owns the Action Plan dependency-order preview (ActionPlanSection,
// below): it is a continuation of these results, not an independent
// analysis, so it is colocated here rather than given its own panel/route —
// selectedRole and the successful CourseDiscoveryData are already
// authoritative in this scope; lifting them elsewhere would just create a
// second copy of state this component already owns.
export function CourseDiscoveryPanel({
  targetRoles,
  run: externalRun,
  selectedRole: externalSelectedRole,
  onSelectedRoleChange,
}: CourseDiscoveryPanelProps) {
  const { slug, session } = useAuth();
  const [internalSelectedRole, setInternalSelectedRole] = useState(targetRoles[0] ?? '');
  const selectedRole = externalSelectedRole ?? internalSelectedRole;
  const setSelectedRole = onSelectedRoleChange ?? setInternalSelectedRole;
  const supportedRoles = useSupportedTargetRoles();
  const internalRun = useAnalysisRun(() =>
    analyzeCourseDiscovery(
      { slug, accessToken: session?.access_token ?? null },
      targetRoles.length > 1 ? selectedRole : null,
    ),
  );
  const { state, trigger } = externalRun ?? internalRun;

  const successData = state.phase === 'done' && state.result.status === 'success' ? state.result.data : null;

  // A fresh Course Discovery result — same role rerun or a new one — means
  // any previously displayed Action Plan no longer describes what's on
  // screen. successData gets a new object identity on every successful run,
  // so bumping a token off that identity and keying ActionPlanSection with
  // it forces a full remount back to its idle state, rather than teaching
  // useAnalysisRun a bespoke invalidation API.
  const [planToken, setPlanToken] = useState(0);
  useEffect(() => {
    if (successData) setPlanToken((token) => token + 1);
  }, [successData]);

  const phase: AnalysisPhase =
    state.phase === 'idle'
      ? 'idle'
      : state.phase === 'loading'
        ? 'loading'
        : state.phase === 'transport-error'
          ? 'failed'
          : state.result.status === 'skipped'
            ? 'skipped'
            : state.result.status === 'failed'
              ? 'failed'
              : 'success';

  const missingFields = state.phase === 'done' ? state.result.missing_fields ?? [] : [];

  return (
    <AnalysisPanel
      title="Course Discovery"
      invitation="Explore courses at your school that could build skills for your career goals."
      phase={phase}
      onRun={trigger}
      missingFields={missingFields}
      failureMessage={analysisFailureMessage(state)}
      headerExtra={
        targetRoles.length > 1 ? (
          <span className="course-discovery-role-select">
            <label htmlFor="course-discovery-target-role">Target role</label>
            <select
              id="course-discovery-target-role"
              value={selectedRole}
              onChange={(event) => setSelectedRole(event.target.value)}
            >
              {targetRoles.map((role) => {
                const unsupported = supportedRoles !== null && !supportedRoles.includes(role);
                return (
                  <option key={role} value={role} disabled={unsupported}>
                    {role}
                  </option>
                );
              })}
            </select>
          </span>
        ) : undefined
      }
    >
      {state.phase === 'done' && state.result.status === 'success' && (
        <>
          <CourseDiscoveryResults data={state.result.data} summary={state.result.summary} />
          <ActionPlanSection
            key={planToken}
            identity={{ slug, accessToken: session?.access_token ?? null }}
            targetRole={state.result.data.target_role}
            courseDiscoveryData={state.result.data}
          />
        </>
      )}
    </AnalysisPanel>
  );
}

function CourseDiscoveryResults({ data, summary }: { data: CourseDiscoveryData; summary: string }) {
  const hasAny =
    data.verified_recommendations.length > 0 ||
    data.prerequisite_blocked.length > 0 ||
    data.requires_verification.length > 0;

  if (!hasAny) {
    return (
      <div>
        <p className="empty-state">No verified course recommendations found from the current evidence.</p>
        {summary && <p className="course-discovery-meta">{summary}</p>}
      </div>
    );
  }

  return (
    <div>
      {data.verified_recommendations.length > 0 && (
        <div className="course-discovery-section">
          <div className="course-discovery-section-title">Recommended courses</div>
          <div className="theme-list">
            {data.verified_recommendations.map((course) => (
              <VerifiedCourseCard key={`${course.institution}:${course.course_code}`} course={course} />
            ))}
          </div>
        </div>
      )}

      {data.prerequisite_blocked.length > 0 && (
        <div className="course-discovery-section">
          <div className="course-discovery-section-title">Courses to work toward</div>
          <div className="theme-list">
            {data.prerequisite_blocked.map((course) => (
              <PrerequisiteBlockedCard key={`${course.institution}:${course.course_code}`} course={course} />
            ))}
          </div>
        </div>
      )}

      {data.requires_verification.length > 0 && (
        <div className="course-discovery-section">
          <div className="course-discovery-section-title">Needs verification</div>
          <div className="theme-list">
            {data.requires_verification.map((course) => (
              <UnresolvedCourseCard key={`${course.institution}:${course.course_code}`} course={course} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function MatchedNeeds({ needs }: { needs: CareerSkillNeed[] }) {
  if (needs.length === 0) return null;
  return (
    <div>
      <div className="gap-column-title">Matches</div>
      <ul className="gap-list">
        {needs.map((need) => (
          <li key={need.need_id} className="gap-list-item gap-list-item--strength">
            {need.skill}
          </li>
        ))}
      </ul>
    </div>
  );
}

function creditLabel(min: number, max: number): string {
  const unit = min === 1 && max === 1 ? 'credit hour' : 'credit hours';
  return min === max ? `${min} ${unit}` : `${min}–${max} ${unit}`;
}

function VerifiedCourseCard({ course }: { course: VerifiedCourseRecommendation }) {
  return (
    <div className="theme-card">
      <div className="theme-header">
        <span className="theme-name">
          {course.course_code} — {course.title}
        </span>
        <span className="course-discovery-status-badge course-discovery-status-badge--ready">
          Ready to consider
        </span>
      </div>
      <p className="theme-summary">{course.ranking_reason}</p>
      {course.skill_alignment_explanation && (
        <p className="theme-summary">{course.skill_alignment_explanation}</p>
      )}
      <MatchedNeeds needs={course.matched_needs} />
      <p className="course-discovery-meta">
        {creditLabel(course.credit_min, course.credit_max)}
        {' · '}
        <a href={course.provenance.source_url} target="_blank" rel="noreferrer">
          Catalog source
        </a>
      </p>
    </div>
  );
}

// missing/in_progress/planned/unknown are mutually exclusive per prerequisite
// code (see PrerequisiteEvaluation in GradusIQ_career/course_discovery/models.py)
// — a code appears in at most one of these lists.
const PREREQ_STATUS_LABEL: Record<string, string> = {
  missing: 'Not yet started',
  in_progress: 'In progress',
  planned: 'Planned',
  unknown: 'Status unclear',
};

function prerequisiteStatusFor(evaluation: PrerequisiteEvaluation, code: string): string {
  if (evaluation.missing_courses.includes(code)) return 'missing';
  if (evaluation.in_progress_courses.includes(code)) return 'in_progress';
  if (evaluation.planned_courses.includes(code)) return 'planned';
  if (evaluation.unknown_courses.includes(code)) return 'unknown';
  return 'unknown';
}

function PrerequisiteList({ evaluation }: { evaluation: PrerequisiteEvaluation }) {
  const { requirement } = evaluation;
  const outstanding = [
    ...evaluation.missing_courses,
    ...evaluation.in_progress_courses,
    ...evaluation.planned_courses,
    ...evaluation.unknown_courses,
  ];

  if (outstanding.length === 0) {
    // ANY-mode with every alternative unresolved some other way, or an
    // UNRESOLVED grammar the backend could not safely parse into codes —
    // never invented; falls back to whatever course_codes evidence exists.
    if (requirement.course_codes.length === 0) return null;
    return (
      <p className="course-discovery-meta">
        Prerequisite: {requirement.course_codes.join(requirement.mode === 'ANY' ? ' or ' : ' and ')}
      </p>
    );
  }

  const connector = requirement.mode === 'ANY' && outstanding.length > 1 ? ' — one of the following' : '';

  return (
    <div>
      <p className="course-discovery-meta">Prerequisite needed{connector}:</p>
      <ul className="course-discovery-prereqs">
        {outstanding.map((code) => {
          const status = prerequisiteStatusFor(evaluation, code);
          return (
            <li key={code} className="course-discovery-prereq">
              <span className="course-discovery-prereq-code">{code}</span>
              <span className="course-discovery-prereq-status">{PREREQ_STATUS_LABEL[status]}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function PrerequisiteBlockedCard({ course }: { course: PrerequisiteBlockedCourse }) {
  return (
    <div className="theme-card">
      <div className="theme-header">
        <span className="theme-name">
          {course.course_code} — {course.title}
        </span>
        <span className="course-discovery-status-badge course-discovery-status-badge--blocked">
          Not yet actionable
        </span>
      </div>
      <p className="theme-summary">Relevant to your target role — another course comes first.</p>
      <MatchedNeeds needs={course.matched_needs} />
      {course.prerequisite_evaluation && <PrerequisiteList evaluation={course.prerequisite_evaluation} />}
    </div>
  );
}

function UnresolvedCourseCard({ course }: { course: UnresolvedCourseCandidate }) {
  return (
    <div className="theme-card">
      <div className="theme-header">
        <span className="theme-name">
          {course.course_code} — {course.title}
        </span>
        <span className="course-discovery-status-badge course-discovery-status-badge--verify">
          Needs verification
        </span>
      </div>
      <p className="theme-summary">
        Course Discovery could not safely confirm this course from current evidence.
      </p>
      <MatchedNeeds needs={course.matched_needs} />
    </div>
  );
}

// ── ACTION PLAN (dependency-order preview) ──────────────────────────────────
// Reads action_plan.edges / dependency_order exactly as the backend returns
// them (GradusIQ_career/action_planning/query.py's dependency_order()). No
// topological sort, no cycle detection, and no pairwise-adjacency inference
// happen here — ordered_node_ids is rendered in the order the backend gave
// it, and a "requires" line only appears when a real edge proves it.

/**
 * Deterministic node_id -> human label lookup, built only from the already-
 * loaded, already-trusted CourseDiscoveryData for this exact result — never
 * from requires_verification (those never become plan nodes; see builder.py).
 * Keys are built the same way action_planning/builder.py's course_node_id()
 * builds a PlanNode's node_id, so a hit is an exact identifier match, not a
 * guess. A miss (institution/course_code that didn't round-trip to the same
 * canonical form) falls back to the code embedded in the node_id itself,
 * never an invented title.
 */
function buildCourseLabelLookup(data: CourseDiscoveryData): Map<string, string> {
  const lookup = new Map<string, string>();
  for (const course of [...data.verified_recommendations, ...data.prerequisite_blocked]) {
    lookup.set(`course:${course.institution}:${course.course_code}`, `${course.course_code} — ${course.title}`);
  }
  return lookup;
}

function displayLabel(nodeId: string, lookup: Map<string, string>): string {
  const known = lookup.get(nodeId);
  if (known) return known;
  const parts = nodeId.split(':');
  return parts.length >= 3 ? parts.slice(2).join(':') : nodeId;
}

function ActionPlanSection({
  identity,
  targetRole,
  courseDiscoveryData,
}: {
  identity: AnalysisIdentity;
  targetRole: string;
  courseDiscoveryData: CourseDiscoveryData;
}) {
  const { state, trigger } = useAnalysisRun<ActionPlanPreviewResponse>(() =>
    analyzeActionPlan(identity, targetRole),
  );
  const labelLookup = useMemo(() => buildCourseLabelLookup(courseDiscoveryData), [courseDiscoveryData]);

  return (
    <div className="action-plan-section">
      <div className="action-plan-divider" role="separator" aria-hidden="true" />
      <h4 className="course-discovery-section-title">Your course path</h4>

      {state.phase === 'idle' && (
        <div className="action-plan-cta">
          <p className="analysis-empty">
            See which of these courses depend on others, and what order to work through them in.
          </p>
          <button type="button" className="btn btn-ghost btn-sm" onClick={trigger}>
            Build my course path
          </button>
        </div>
      )}

      {state.phase === 'loading' && (
        <div className="analysis-loading" role="status" aria-live="polite">
          <span className="spinner" aria-hidden="true" />
          <p>Working out the dependency order for your course path…</p>
        </div>
      )}

      {state.phase === 'transport-error' && (
        <div className="analysis-failed">
          <p>{state.message}</p>
          <button
            type="button"
            className="btn btn-ghost btn-sm analysis-failed-retry"
            onClick={trigger}
          >
            Try again
          </button>
        </div>
      )}

      {state.phase === 'done' && (
        <ActionPlanResultView result={state.result} labelLookup={labelLookup} onRetry={trigger} />
      )}
    </div>
  );
}

function ActionPlanResultView({
  result,
  labelLookup,
  onRetry,
}: {
  result: ActionPlanPreviewResponse;
  labelLookup: Map<string, string>;
  onRetry(): void;
}) {
  // Precondition not met (e.g. role no longer confirmed) or the Course
  // Discovery re-run inside /action-plan itself failed — same FeatureResult
  // shape every other analyze endpoint uses, distinguished here by the
  // absence of action_plan rather than a feature-name check (the skip path
  // reports feature "COURSE_DISCOVERY", not "ACTION_PLAN").
  if (!('action_plan' in result)) {
    if (result.status === 'skipped') {
      return (
        <div className="analysis-skipped">
          <p>{result.summary}</p>
        </div>
      );
    }
    return (
      <div className="analysis-failed">
        <p>{result.errors[0] ?? result.summary}</p>
        <button type="button" className="btn btn-ghost btn-sm analysis-failed-retry" onClick={onRetry}>
          Try again
        </button>
      </div>
    );
  }

  const { action_plan, dependency_order } = result;

  // action_plan.execution_status === "ERROR" (e.g. a cycle was detected) --
  // typed failure, safe_message only, never error_class.
  if (result.status === 'failed' || dependency_order === null) {
    return (
      <div className="analysis-failed">
        <p>{action_plan.failure?.safe_message ?? action_plan.summary}</p>
        <button type="button" className="btn btn-ghost btn-sm analysis-failed-retry" onClick={onRetry}>
          Try again
        </button>
      </div>
    );
  }

  // dependency_order.status === "ERROR" can happen even when the plan itself
  // built successfully -- a distinct failure from the one above.
  if (dependency_order.status === 'ERROR') {
    return (
      <div className="analysis-failed">
        <p>
          {dependency_order.failure?.safe_message ??
            'The dependency order could not be determined safely.'}
        </p>
        <button type="button" className="btn btn-ghost btn-sm analysis-failed-retry" onClick={onRetry}>
          Try again
        </button>
      </div>
    );
  }

  return <DependencyOrderView plan={action_plan} order={dependency_order} labelLookup={labelLookup} />;
}

function DependencyOrderView({
  plan,
  order,
  labelLookup,
}: {
  plan: UnifiedActionPlan;
  order: DependencyOrderResult;
  labelLookup: Map<string, string>;
}) {
  const requiresByDependent = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const edge of plan.edges) {
      if (edge.relation !== 'requires') continue;
      const list = map.get(edge.from_node_id) ?? [];
      list.push(edge.to_node_id);
      map.set(edge.from_node_id, list);
    }
    return map;
  }, [plan.edges]);

  const label = (nodeId: string) => displayLabel(nodeId, labelLookup);
  const isEmpty = order.ordered_node_ids.length === 0 && order.unconstrained_node_ids.length === 0;

  return (
    <div>
      {isEmpty && <p className="empty-state">No course actions to sequence yet.</p>}

      {order.ordered_node_ids.length > 0 && (
        <div className="course-discovery-section">
          <div className="course-discovery-section-title">Suggested dependency order</div>
          {/* A topological order, not a chain: item 2 does not necessarily
              require item 1 directly -- only the "Requires" line under an
              item, drawn from a real `requires` edge, states that. */}
          <ol className="action-plan-ordered-list">
            {order.ordered_node_ids.map((nodeId) => {
              const requires = requiresByDependent.get(nodeId) ?? [];
              return (
                <li key={nodeId} className="action-plan-ordered-item">
                  <span className="action-plan-item-label">{label(nodeId)}</span>
                  {requires.length > 0 && (
                    <span className="action-plan-item-requires">
                      Requires: {requires.map(label).join(', ')}
                    </span>
                  )}
                </li>
              );
            })}
          </ol>
        </div>
      )}

      {order.unconstrained_node_ids.length > 0 && (
        <div className="course-discovery-section">
          <div className="course-discovery-section-title">Can be considered independently</div>
          <p className="course-discovery-meta">No prerequisite order constrains these.</p>
          <ul className="action-plan-unconstrained-list">
            {order.unconstrained_node_ids.map((nodeId) => (
              <li key={nodeId}>{label(nodeId)}</li>
            ))}
          </ul>
        </div>
      )}

      <div
        className={
          order.completeness === 'COMPLETE'
            ? 'action-plan-banner action-plan-banner--complete'
            : 'action-plan-banner action-plan-banner--provisional'
        }
      >
        <p className="action-plan-banner-status">
          {order.completeness === 'COMPLETE' ? 'Dependency order complete' : 'Dependency order provisional'}
        </p>
        <p className="action-plan-banner-detail">
          {order.completeness === 'COMPLETE'
            ? 'The prerequisites currently known for these actions can be represented in this course path.'
            : 'Some prerequisite choices still need to be resolved.'}
        </p>
        {order.limitations.length > 0 && (
          <ul className="action-plan-limitation-list">
            {order.limitations.map((limitation, index) => (
              <li key={`${limitation.node_id}-${limitation.reason_type}-${index}`}>
                <LimitationText limitation={limitation} label={label} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function LimitationText({
  limitation,
  label,
}: {
  limitation: DependencyOrderLimitation;
  label(nodeId: string): string;
}) {
  const nodeLabel = label(limitation.node_id);
  if (limitation.reason_type === 'ANY_PREREQUISITE') {
    return (
      <span>
        {nodeLabel} requires one of: {limitation.course_codes.join(' / ')}
      </span>
    );
  }
  if (limitation.reason_type === 'UNKNOWN_COURSE_STATE') {
    return <span>We couldn't confirm your status for: {limitation.course_codes.join(', ')}</span>;
  }
  return (
    <span>
      {nodeLabel}: this prerequisite could not be represented safely from the catalog evidence.
      {limitation.course_codes.length > 0 ? ` (${limitation.course_codes.join(', ')})` : ''}
    </span>
  );
}
