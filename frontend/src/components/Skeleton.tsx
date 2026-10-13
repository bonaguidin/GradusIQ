/**
 * Placeholder rows shaped like the list that is loading: a short title bar
 * and a longer line under it, per row, breathing on the shared skeleton
 * pulse. The label is what a screen reader hears in place of the shapes.
 */
export function SkeletonRows({ label, rows = 3, variant = 'rows' }: { label: string; rows?: number; variant?: 'rows' | 'cards' }) {
  return (
    <div className={`skeleton-block skeleton-block--${variant}`} role="status" aria-live="polite">
      <span className="sr-only">{label}</span>
      <ul className="skeleton-list" aria-hidden="true">
        {Array.from({ length: rows }, (_, slot) => (
          <li key={slot} className="skeleton-item" />
        ))}
      </ul>
    </div>
  );
}
