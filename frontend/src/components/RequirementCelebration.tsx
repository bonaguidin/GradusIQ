import { useEffect, useRef, useState } from 'react';
import type { RequirementGroupResult } from '../api/requirementSatisfaction.mjs';
import {
  celebrationMessage,
  celebrationStorageKey,
  parseCelebrated,
  planCelebration,
  satisfiedLeafRequirements,
} from '../lib/requirementCelebration.mjs';

/**
 * Works out, once per dashboard visit, whether a degree requirement has been
 * finished since this browser last looked, and returns the line to show.
 * The rules (once ever, silent on first sight) live in
 * lib/requirementCelebration.mjs.
 *
 * `active` holds the check until the student is on Overview: the burst plays
 * on the ring there, so recording it as celebrated while they sit on another
 * tab would spend the moment where nobody can see it.
 *
 * Storage failures (private mode, blocked site data) just mean no celebration;
 * nothing here is load-bearing.
 */
export function useRequirementCelebration({
  studentId,
  groups,
  ready,
  active,
  progress,
}: {
  studentId: string | null;
  groups: RequirementGroupResult[];
  ready: boolean;
  active: boolean;
  progress: { satisfied: number; total: number };
}) {
  const [message, setMessage] = useState<string | null>(null);
  const checked = useRef(false);

  useEffect(() => {
    if (checked.current || !ready || !active || !studentId) return;
    checked.current = true;
    try {
      const key = celebrationStorageKey(studentId);
      const plan = planCelebration(parseCelebrated(window.localStorage.getItem(key)), satisfiedLeafRequirements(groups));
      window.localStorage.setItem(key, JSON.stringify(plan.remember));
      if (plan.fresh.length > 0) setMessage(celebrationMessage(plan.fresh, progress));
    } catch {
      // No storage, no celebration.
    }
  }, [ready, active, studentId, groups, progress]);

  return { message, dismiss: () => setMessage(null) };
}

/**
 * The line that goes with the ring's burst. Same quiet banner shape as
 * DashboardSuccessNotice, in gold rather than green: it marks a milestone,
 * it does not confirm an action. Nothing is focused and nothing overlays.
 */
export function RequirementCelebration({ message, onDismiss }: { message: string | null; onDismiss: () => void }) {
  // Always-mounted live region, filled a tick later, for the same reason
  // DashboardSuccessNotice does it: a region created with its text already in
  // place is often not announced.
  const [shown, setShown] = useState<string | null>(null);
  useEffect(() => {
    const id = window.setTimeout(() => setShown(message), 0);
    return () => window.clearTimeout(id);
  }, [message]);

  return (
    <div className="req-celebrate-region" role="status" aria-live="polite">
      {shown && (
        <div className="req-celebrate">
          <span className="req-celebrate-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="16" height="16">
              <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z" />
            </svg>
          </span>
          <p className="req-celebrate-text">{shown}</p>
          <button type="button" className="dash-notice-dismiss" onClick={onDismiss} aria-label="Dismiss this message">
            ×
          </button>
        </div>
      )}
    </div>
  );
}
