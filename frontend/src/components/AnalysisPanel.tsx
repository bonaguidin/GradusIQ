import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { MissingField } from '../types/analysis';
import { useProfileFieldRequest } from './profile/ProfileCompletionContext';

export type AnalysisPhase = 'idle' | 'loading' | 'skipped' | 'failed' | 'success';

/**
 * Where a student goes to fill in what an analysis is missing.
 *
 * A placeholder: the route does not exist yet, and App.tsx's catch-all
 * currently redirects it to /login. Named here as one constant so the surface
 * that claims it later changes this line and nothing else. The missing field's
 * path rides along as a query parameter for that page to focus on if it wants
 * to -- a hint it is free to ignore, deliberately not a route segment, so
 * nothing here constrains the shape that page ends up taking.
 */
export const PROFILE_COMPLETION_PATH = '/profile/complete';

export function profileCompletionHref(path: string): string {
  return `${PROFILE_COMPLETION_PATH}?field=${encodeURIComponent(path)}`;
}

/**
 * The gaps the profile-completion surface cannot close.
 *
 * Skills and work experience are parsed from the résumé and edited on /resume;
 * the completion form deliberately owns neither. Sending these to the modal
 * opened a dialog with no field for the thing that was missing, so they route
 * to the surface that can actually fix them instead.
 */
const RESUME_OWNED_PATHS = new Set(['career.skills_self_reported', 'career.work_experience']);

interface AnalysisPanelProps {
  title: string;
  invitation: string;
  phase: AnalysisPhase;
  onRun(): void;
  missingFields?: MissingField[];
  /**
   * Why the run failed, when it did. Optional and additive: AnalysisPhase and
   * the FeatureStatus contract behind it are untouched, so nothing that keys
   * off 'failed' changes. Absent it, the generic sentence still renders.
   */
  failureMessage?: string;
  /**
   * A control that must be set before running (e.g. Course Discovery's
   * target-role picker, when a student has more than one confirmed role).
   * Renders in the header, before the run button. Optional and additive --
   * FIT/GAP/SHIFT/Professor Comments pass nothing and are unaffected.
   */
  headerExtra?: ReactNode;
  /**
   * True while a manual re-run is in flight AND a 'done' result is already
   * showing (see useCachedAnalysisRun). When set, the previous `children`
   * stay rendered as-is -- this does not switch to the phase === 'loading'
   * full-panel view -- and a small spinner + label appear near the header
   * instead. Optional and additive: callers that don't pass it (or pass
   * `false`) render exactly as before.
   */
  refreshing?: boolean;
  /**
   * Set when a re-run triggered from an already-'done' panel fails. Rendered
   * as a small inline notice alongside the existing (still-shown) content,
   * not a replacement for it -- distinct from the phase === 'failed' view,
   * which only applies when there is no prior result to fall back to.
   */
  refreshError?: string;
  /**
   * Set when something other than this panel's own state should block the
   * run button -- Career Intelligence gates FIT/GAP/SHIFT to one live call
   * at a time, so a sibling panel already running disables this one and
   * this reason takes the place of the idle invitation. Optional and
   * additive: every other caller passes nothing and renders exactly as
   * before.
   */
  blockedReason?: string;
  children?: ReactNode;
}

// Shared shell for read-only AI-generated result panels (GAP, Professor
// Comment Analyzer). Mirrors EditableSection's card + header-actions layout
// so these read-only panels feel like part of the same system as the
// editable career sections, without offering Edit/Save/Cancel — these are
// AI-generated, not user-editable fields.
export function AnalysisPanel({
  title,
  invitation,
  phase,
  onRun,
  missingFields = [],
  failureMessage,
  headerExtra,
  refreshing = false,
  refreshError,
  blockedReason,
  children,
}: AnalysisPanelProps) {
  const requestProfileField = useProfileFieldRequest();
  return (
    <div className="card analysis-panel">
      <div className="editable-section-header">
        <h3 className="editable-section-title">
          {title}
          {refreshing && (
            <span className="analysis-refreshing" role="status" aria-live="polite">
              <span className="spinner-small" aria-hidden="true" />
              Re-running…
            </span>
          )}
        </h3>
        <div className="editable-section-actions">
          {headerExtra}
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onRun}
            disabled={phase === 'loading' || refreshing || Boolean(blockedReason)}
            aria-busy={phase === 'loading' || refreshing}
          >
            {phase === 'loading' ? (
              <span className="btn-loading">
                <span className="spinner-small" aria-hidden="true" />
                Analyzing…
              </span>
            ) : phase === 'idle' ? (
              'Run analysis'
            ) : (
              'Re-run analysis'
            )}
          </button>
        </div>
      </div>

      {phase === 'idle' && <p className="analysis-empty">{blockedReason ?? invitation}</p>}

      {blockedReason && phase !== 'idle' && phase !== 'loading' && !refreshing && (
        <p className="analysis-blocked-note">{blockedReason}</p>
      )}

      {phase === 'loading' && (
        <div className="analysis-loading" role="status" aria-live="polite">
          <span className="spinner" aria-hidden="true" />
          <p>Running this analysis against a live model — this can take a moment.</p>
        </div>
      )}

      {phase === 'skipped' && (
        <div className="analysis-skipped">
          <p>Your profile is missing information this analysis needs:</p>
          <ul className="section-errors">
            {missingFields.map((field) => (
              <li key={field.path} className="section-error-item">
                <span className="missing-field-label">{field.label}</span>
                {/* One gap, one action, aimed at THAT gap. This used to open a
                    dialog listing every field the surface owned, so clicking
                    the line that said "Target roles" produced a form whose
                    first question was about graduation. The link now goes to
                    the field named on the line it sits on. */}
                {RESUME_OWNED_PATHS.has(field.path)
                  ? <Link className="missing-field-link" to="/resume">Review résumé</Link>
                  : requestProfileField
                    ? <button className="missing-field-link" type="button" onClick={(event) => requestProfileField({ path: field.path, feature: title.match(/\((FIT|GAP|SHIFT)\)/)?.[1] ?? title, trigger: event.currentTarget })}>Add this</button>
                    : <Link className="missing-field-link" to={profileCompletionHref(field.path)}>Add this</Link>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {phase === 'failed' && (
        <div className="analysis-failed">
          {/* analysisFailure owns complete recovery guidance so each failure
              renders one coherent instruction rather than competing retries. */}
          <p>{failureMessage ?? 'Something went wrong generating this analysis.'}</p>
        </div>
      )}

      {phase === 'success' && children}

      {refreshError && (
        <div className="analysis-refresh-error">
          <p>{refreshError}</p>
        </div>
      )}
    </div>
  );
}
