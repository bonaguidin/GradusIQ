import type { ReactNode } from 'react';

const ICON_PATHS = {
  // A calendar page: nothing scheduled.
  calendar: 'M7 3v3M17 3v3M4 9h16M5 5h14a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z',
  // A target: no role matched yet.
  target: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 12h.01',
  // Rising bars: no readiness check yet.
  bars: 'M6 20v-6M12 20V10M18 20V4',
  // An open book: no courses to show.
  book: 'M12 6.5C10.5 5 8 4.5 4 4.5v13c4 0 6.5.5 8 2 1.5-1.5 4-2 8-2v-13c-4 0-6.5.5-8 2zM12 6.5v13',
  // A path between two points: nothing to sequence or schedule.
  route: 'M6 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM8 17h7a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h7',
} as const;

export type EmptyStateIcon = keyof typeof ICON_PATHS;

/**
 * The one empty-state block: an icon, one line saying what is missing, and
 * at most one action that fills it. The line keeps the .empty-state class
 * every plain empty state already uses, so its copy and tests stay put.
 */
export function EmptyState({ icon, children, action }: { icon: EmptyStateIcon; children: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty-block">
      <span className="empty-block-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
          <path d={ICON_PATHS[icon]} />
        </svg>
      </span>
      <p className="empty-state">{children}</p>
      {action}
    </div>
  );
}
