import { Counter } from './LedgerBar';

export interface TranscriptLedgerProps {
  courses: number;
  /** Pre-formatted, because credits are a 2dp decimal, not a count. */
  credits: string;
  catalogChecks: number;
  repeatExclusions: number;
  onJumpToCheck(): void;
}

/**
 * The transcript twin of LedgerBar.
 *
 * The Counter/bump mechanism and the progress bar are the shared parts and are
 * imported, not copied. What differs is what there is to count: the resume
 * ledger's read / not-found / edited describes fields the parser did or did
 * not find, which is the wrong frame for a transcript, where every course has
 * every field and the open questions are instead "how many courses, worth how
 * many credits, how many need a catalog check, how many are excluded by the
 * repeat policy".
 *
 * The progress bar tracks catalog coverage rather than filled fields, for the
 * same reason: it is the transcript's actual measure of how much of this
 * record is grounded in known data.
 */
export function TranscriptLedger({
  courses,
  credits,
  catalogChecks,
  repeatExclusions,
  onJumpToCheck,
}: TranscriptLedgerProps) {
  const matchedRatio = courses === 0 ? 0 : (courses - catalogChecks) / courses;
  const noChecks = catalogChecks === 0;

  return (
    <div className="rv-ledger">
      <div className="rv-ledger-counts">
        <Counter value={courses} label="courses read" />
        <Counter value={credits} label="credits attempted" />
        <Counter value={catalogChecks} label="need a catalog check" tone="gap" />
        {repeatExclusions > 0 && (
          <Counter value={repeatExclusions} label="excluded by repeats" />
        )}
      </div>

      <div className="rv-ledger-actions">
        <button
          type="button"
          className="rv-jump"
          onClick={onJumpToCheck}
          disabled={noChecks}
          aria-label={
            noChecks
              ? 'Every course matched the catalog'
              : `Jump to the next of ${String(catalogChecks)} courses needing a catalog check`
          }
        >
          {noChecks ? '✓ all matched' : '↓ next check'}
        </button>
      </div>

      <div
        className="rv-progress"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(matchedRatio * 100)}
        aria-label="Courses matched to the catalog"
      >
        <div className="rv-progress-fill" style={{ transform: `scaleX(${String(matchedRatio)})` }} />
      </div>
    </div>
  );
}
