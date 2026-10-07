import { useAuth } from '../auth/useAuth';
import { analyzeShift } from '../api/analysis';
import { analysisFailureMessage, type AnalysisRunState } from '../hooks/useAnalysisRun';
import { useCachedAnalysisRun } from '../hooks/useCachedAnalysisRun';
import type {
  FeatureResult,
  ShiftAnalysisData,
  ShiftTaskShift,
  ShiftDurableSkill,
  ShiftAdjacentPath,
} from '../types/analysis';
import { AnalysisPanel, type AnalysisPhase } from './AnalysisPanel';

export interface ShiftAnalysisRun {
  state: AnalysisRunState<FeatureResult<ShiftAnalysisData>>;
  trigger: () => void;
  /** From useCachedAnalysisRun -- see GapAnalysisRun. */
  refreshing?: boolean;
  refreshError?: string;
  /** From useSequencedAnalysisRuns -- see AnalysisPanel's blockedReason. */
  blockedReason?: string;
}

interface ShiftAnalysisPanelProps {
  /**
   * Lets a parent (the Career Snapshot sub-tab) share this exact run state
   * instead of each holding its own. Omitted by every other caller, which
   * keeps its own internal useAnalysisRun instance exactly as before.
   */
  run?: ShiftAnalysisRun;
}

// SHIFT trend-aware guidance panel — data shape is shift.py's output_contract
// (role_evolution_summary, task_shifts[], durable_skills[], adjacent_paths[],
// ai_fluency_guidance[]). PROVISIONAL: unvalidated against a real (non-mocked)
// model response — see frontend/src/types/analysis.ts.
export function ShiftAnalysisPanel({ run: externalRun }: ShiftAnalysisPanelProps = {}) {
  const { slug, session } = useAuth();
  const internalRun = useCachedAnalysisRun('shift', () =>
    analyzeShift({ slug, accessToken: session?.access_token ?? null }),
  );
  const { state, trigger, refreshing, refreshError, blockedReason } = externalRun ?? internalRun;

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
      title="Trend Guidance (SHIFT)"
      invitation="See how your target roles are evolving — what's changing, what stays durable, and adjacent paths worth exploring."
      phase={phase}
      onRun={trigger}
      missingFields={missingFields}
      failureMessage={analysisFailureMessage(state)}
      refreshing={refreshing}
      refreshError={refreshError}
      blockedReason={blockedReason}
    >
      {state.phase === 'done' && state.result.status === 'success' && (
        <ShiftResult data={state.result.data} summary={state.result.summary} />
      )}
    </AnalysisPanel>
  );
}

function ShiftResult({ data, summary }: { data: ShiftAnalysisData; summary: string }) {
  // A "success" status is a contract, not a guarantee -- a response cut
  // short mid-OOM can still parse as JSON with a field missing.
  const taskShifts = data.task_shifts ?? [];
  const durableSkills = data.durable_skills ?? [];
  const adjacentPaths = data.adjacent_paths ?? [];
  const aiFluencyGuidance = data.ai_fluency_guidance ?? [];

  return (
    <div>
      <p className="gap-summary">{data.role_evolution_summary || summary}</p>

      <div className="gap-columns">
        <div>
          <div className="gap-column-title">What's Changing</div>
          {taskShifts.length > 0 ? (
            <div className="theme-list">
              {taskShifts.map((shift, idx) => (
                <TaskShiftCard key={idx} shift={shift} />
              ))}
            </div>
          ) : (
            <p className="empty-state">None identified.</p>
          )}
        </div>

        <div>
          <div className="gap-column-title">Durable Skills</div>
          {durableSkills.length > 0 ? (
            <div className="theme-list">
              {durableSkills.map((skill, idx) => (
                <DurableSkillCard key={idx} skill={skill} />
              ))}
            </div>
          ) : (
            <p className="empty-state">None identified.</p>
          )}
        </div>
      </div>

      {adjacentPaths.length > 0 && (
        <div className="gap-section">
          <div className="gap-column-title">Adjacent Paths</div>
          <div className="theme-list">
            {adjacentPaths.map((path, idx) => (
              <AdjacentPathCard key={idx} path={path} />
            ))}
          </div>
        </div>
      )}

      {aiFluencyGuidance.length > 0 && (
        <div>
          <div className="gap-column-title">AI Fluency Guidance</div>
          <ul className="gap-list">
            {aiFluencyGuidance.map((guidance, idx) => (
              <li key={idx} className="gap-list-item">
                {guidance}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function TaskShiftCard({ shift }: { shift: ShiftTaskShift }) {
  return (
    <div className="theme-card">
      <div className="theme-header">
        <span className="theme-name">{shift.task}</span>
      </div>
      <p className="theme-summary">{shift.changing}</p>
      <p className="gap-item-why">{shift.meaning}</p>
    </div>
  );
}

function DurableSkillCard({ skill }: { skill: ShiftDurableSkill }) {
  return (
    <div className="theme-card">
      <div className="theme-header">
        <span className="theme-name">{skill.task}</span>
      </div>
      <p className="theme-summary">{skill.reason}</p>
    </div>
  );
}

function AdjacentPathCard({ path }: { path: ShiftAdjacentPath }) {
  return (
    <div className="theme-card">
      <div className="theme-header">
        <span className="theme-name">{path.path}</span>
      </div>
      <p className="theme-summary">{path.relevance}</p>
      <p className="gap-item-why">{path.driver}</p>
    </div>
  );
}
