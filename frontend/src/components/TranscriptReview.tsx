import { useCallback, useMemo, useState } from 'react';
import { confirmTranscript, patchTranscriptRecord } from '../api/transcript';
import { GLYPH_EDITED, GLYPH_EMPTY, GLYPH_READ, isEmptyValue } from '../lib/resumeApi.mjs';
import type { ReviewRow } from '../lib/resumeApi.mjs';
import {
  TRANSCRIPT_SECTION,
  parseCreditHours,
  transcriptChangedFields,
  transcriptFieldChanged,
} from '../lib/transcriptApi.mjs';
import type {
  TranscriptConfirmResult,
  TranscriptRecord,
  TranscriptReviewResult,
  TranscriptUploadResult,
} from '../lib/transcriptApi.mjs';
import { CommitBar } from './review/CommitBar';
import { CrossCheckNotice } from './review/CrossCheckNotice';
import { EntryCard } from './review/EntryCard';
import { RepeatExclusions } from './review/RepeatExclusions';
import { TermGroup } from './review/TermGroup';
import { TranscriptLedger } from './review/TranscriptLedger';

export interface TranscriptReviewProps {
  accessToken: string;
  review: TranscriptReviewResult & { ok: true };
  uploadResult?: TranscriptUploadResult | null;
  sourceName?: string;
  onConfirmed(result: TranscriptConfirmResult): void;
}

interface RowState {
  message: string | null;
  tone: 'error' | 'saved';
  locked: boolean;
}

const DATE_FMT = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: 'short',
  day: '2-digit',
});

/** Sorts a term after every resolved one. Ported from the previous grouping. */
const UNSEQUENCED = 9999;
const UNRESOLVED_KEY = 'unresolved';

/**
 * Provenance glyph for a transcript field.
 *
 * Cannot be the shared fieldGlyph: that compares with a strict ===, and
 * credit_hours arrives from the backend as the string "3.00" while the number
 * FieldRow hands back is 3. A pure reformat would otherwise show the ✎ that
 * means "you changed this", which is a lie about where the value came from.
 */
function transcriptGlyph(original: ReviewRow, draft: ReviewRow, fieldName: string) {
  const changed = transcriptFieldChanged(original, draft, fieldName);
  if (isEmptyValue(draft[fieldName])) return changed ? GLYPH_EMPTY : null;
  return changed ? GLYPH_EDITED : GLYPH_READ;
}

/**
 * Draft rows keep credit_hours as a NUMBER, parsed once on the way in.
 *
 * The decision is that the string/number boundary lives at the edit surface
 * and nowhere else. Parsing here means FieldRow's number type receives what it
 * expects, and formatCreditHours puts it back to the backend's 2dp string at
 * the save boundary -- see transcriptChangedFields.
 */
function draftOf(row: TranscriptRecord): ReviewRow {
  return { ...row, credit_hours: parseCreditHours(row.credit_hours) } as unknown as ReviewRow;
}

export function TranscriptReview({
  accessToken,
  review,
  uploadResult,
  sourceName,
  onConfirmed,
}: TranscriptReviewProps) {
  const [records, setRecords] = useState<TranscriptRecord[]>(review.records);
  const [drafts, setDrafts] = useState<Record<string, ReviewRow>>(() =>
    Object.fromEntries(review.records.map((row) => [row.id, draftOf(row)])),
  );
  /**
   * The rows exactly as the transcript parse produced them. Glyphs compare
   * against this, never against `records` -- which is replaced by the server's
   * saved row after each PATCH, so diffing against it would erase the edit
   * marker the instant the edit succeeded. Same reasoning as CareerReview's
   * baseline, and the same reason it is a separate piece of state.
   */
  const [baseline] = useState<Record<string, ReviewRow>>(() =>
    Object.fromEntries(review.records.map((row) => [row.id, draftOf(row)])),
  );
  const [rowStates, setRowStates] = useState<Record<string, RowState>>({});
  const [confirming, setConfirming] = useState(false);
  const [justSaved, setJustSaved] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [confirmBlocked, setConfirmBlocked] = useState<string | null>(null);

  const terms = useMemo(() => new Map(review.terms.map((term) => [term.id, term])), [review.terms]);
  const institution = review.institutions[0]?.name;

  /**
   * Courses grouped by term, ported from the previous implementation:
   * a Map keyed on term_id, an 'unresolved' bucket for rows whose term could
   * not be resolved, ordered by the term's own sequence with unsequenced
   * groups last. Only the presentation below is new.
   */
  const groups = useMemo(() => {
    const grouped = new Map<string, TranscriptRecord[]>();
    for (const row of records) {
      const key = row.term_id ?? UNRESOLVED_KEY;
      grouped.set(key, [...(grouped.get(key) ?? []), row]);
    }
    return [...grouped.entries()].sort(
      ([a], [b]) =>
        (terms.get(a)?.sequence ?? UNSEQUENCED) - (terms.get(b)?.sequence ?? UNSEQUENCED),
    );
  }, [records, terms]);

  const creditsOf = useCallback(
    (rows: TranscriptRecord[]) =>
      rows
        .reduce((sum, row) => sum + (parseCreditHours(drafts[row.id]?.credit_hours ?? row.credit_hours) ?? 0), 0)
        .toFixed(2),
    [drafts],
  );

  const catalogChecks = records.filter((row) => row.needs_catalog_review).length;

  const setRowState = useCallback((id: string, state: RowState | null) => {
    setRowStates((prev) => {
      const next = { ...prev };
      if (state === null) delete next[id];
      else next[id] = state;
      return next;
    });
  }, []);

  /**
   * Save one course's changes.
   *
   * The same shape as CareerReview.commit, because transcript/review.py raises
   * the same four conditions by deliberate design: not-found, already-
   * confirmed, conflict, and invalid. Each is handled the same way here --
   * drop the row, lock it, or keep the typed value and say it did not save.
   */
  const commit = useCallback(
    async (row: TranscriptRecord, overrides?: Record<string, unknown>): Promise<boolean> => {
      const stored = drafts[row.id];
      if (!stored) return false;
      const draft = overrides ? { ...stored, ...overrides } : stored;

      const changes = transcriptChangedFields(row as unknown as ReviewRow, draft);
      if (Object.keys(changes).length === 0) return false;

      const result = await patchTranscriptRecord(accessToken, row.id, changes);

      if (result.ok && result.record) {
        const saved = result.record;
        setRecords((prev) => prev.map((item) => (item.id === saved.id ? saved : item)));
        setDrafts((prev) => ({ ...prev, [saved.id]: draftOf(saved) }));
        setRowState(row.id, null);
        return true;
      }

      if (result.kind === 'not_found') {
        setRecords((prev) => prev.filter((item) => item.id !== row.id));
        setDrafts((prev) => {
          const next = { ...prev };
          delete next[row.id];
          return next;
        });
        setRowState(row.id, null);
        return false;
      }

      if (result.kind === 'already_confirmed') {
        setDrafts((prev) => ({ ...prev, [row.id]: draftOf(row) }));
        setRowState(row.id, { message: result.message, tone: 'error', locked: true });
        return false;
      }

      setRowState(row.id, { message: result.message, tone: 'error', locked: false });
      return false;
    },
    [accessToken, drafts, setRowState],
  );

  async function handleConfirm() {
    setConfirming(true);
    setConfirmError(null);
    setConfirmBlocked(null);
    const result = await confirmTranscript(accessToken);
    if (result.ok) {
      setJustSaved(true);
      // `confirming` is deliberately NOT cleared on success. onConfirmed hands
      // over to the dashboard, and the handover includes re-reading the
      // canonical profile -- dropping the overlay here would expose a review
      // screen that still looks editable but describes records that are now
      // confirmed and gone. It clears when this screen unmounts.
      //
      // 650ms, not 450: CommitBar's success state (the button's own slam +
      // ring) runs up to 600ms, and the point of adding it was for the
      // student to actually see it before the screen moves on.
      window.setTimeout(() => onConfirmed(result), 650);
      return;
    }
    // A pending grade scale is not a failed action -- it is a state of our
    // data that the student can do nothing about, and the backend models it
    // as its own 409 code for exactly that reason. Rendering it as an error
    // beside a retry button would invite them to keep clicking.
    if (result.kind === 'grade_scale_unverified') setConfirmBlocked(result.message);
    else setConfirmError(result.message);
    // Every non-ok outcome -- API failure, timeout, block, validation -- lands
    // here: the screen stays put, usable, and (except when blocked) retryable.
    setConfirming(false);
  }

  const jumpToCheck = useCallback(() => {
    const card = document.querySelector<HTMLElement>('[data-catalog-check]');
    if (!card) return;
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    card.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'center' });
  }, []);

  const totalCredits = creditsOf(records);
  const editedCount = records.filter((row) =>
    TRANSCRIPT_SECTION.fields.some((field) =>
      transcriptFieldChanged(baseline[row.id], drafts[row.id], field.name),
    ),
  ).length;

  return (
    <div className="rv-bg">
      <div className="rv-page">
        <header className="rv-masthead">
          <div className="rv-masthead-top">
            <span className="rv-wordmark">GradusIQ</span>
            {(sourceName || institution) && (
              <span className="rv-provenance">
                {sourceName && <span className="rv-provenance-file">{sourceName}</span>}
                {institution && <span>{institution}</span>}
                <span>read {DATE_FMT.format(new Date())}</span>
              </span>
            )}
          </div>
          {/* The rv-masthead STRUCTURE is the parity that was missing (wordmark,
              provenance, glyph legend). The headline stays transcript-specific
              rather than borrowing the resume screen's wording. */}
          <h1 className="rv-headline">Verify your academic record</h1>
          <p className="rv-standfirst">
            Every course below came off your transcript and none of it is saved yet. A{' '}
            <span className="rv-inline-glyph">·</span> means we read it as-is, a{' '}
            <span className="rv-inline-glyph rv-glyph-edited">✎</span> means you changed it. Click
            anything to correct it — edits save as you go.
          </p>
        </header>

        <TranscriptLedger
          courses={records.length}
          credits={totalCredits}
          catalogChecks={catalogChecks}
          repeatExclusions={review.excludedByRepeat.length}
          onJumpToCheck={jumpToCheck}
        />

        {uploadResult && <CrossCheckNotice crossCheck={uploadResult.crossCheck} />}

        {groups.map(([termId, termRows]) => (
          <TermGroup
            key={termId}
            label={terms.get(termId)?.label ?? 'Term not resolved'}
            count={termRows.length}
            credits={creditsOf(termRows)}
          >
            {termRows.map((row, index) => {
              const state = rowStates[row.id];
              return (
                <EntryCard
                  key={row.id}
                  table="course_records"
                  section={TRANSCRIPT_SECTION}
                  original={baseline[row.id] ?? (row as unknown as ReviewRow)}
                  draft={drafts[row.id] ?? (row as unknown as ReviewRow)}
                  index={index}
                  locked={state?.locked ?? false}
                  message={state?.message ?? null}
                  tone={state?.tone ?? 'saved'}
                  glyphFor={transcriptGlyph}
                  // Every course has every field, so an empty value is a
                  // correction to make in place, not a gap to invite.
                  hideGaps
                  flags={<CourseFlags row={row} />}
                  onChange={(fieldName, next) =>
                    setDrafts((prev) => ({
                      ...prev,
                      [row.id]: { ...prev[row.id], [fieldName]: next },
                    }))
                  }
                  onCommit={(overrides) => commit(row, overrides)}
                />
              );
            })}
          </TermGroup>
        ))}

        <RepeatExclusions rows={review.excludedByRepeat} terms={terms} />
      </div>

      <CommitBar
        counters={{
          read: records.length,
          gaps: catalogChecks,
          edited: editedCount,
          total: records.length,
          filledRatio: 1,
        }}
        confirming={confirming}
        justSaved={justSaved}
        error={confirmError}
        blocked={confirmBlocked}
        confirmLabel={`Confirm ${String(records.length)} courses`}
        statusOverride={
          catalogChecks > 0
            ? `Confirming saves ${String(records.length)} courses worth ${totalCredits} credits. ${String(catalogChecks)} still ${catalogChecks === 1 ? 'needs' : 'need'} a catalog check.`
            : `Confirming saves ${String(records.length)} courses worth ${totalCredits} credits.`
        }
        onConfirm={() => {
          void handleConfirm();
        }}
      />
    </div>
  );
}

/**
 * Card-level annotations for one course.
 *
 * Card level, not field level: needs_catalog_review is a fact about the course
 * record as a whole, and no field-level provenance pattern exists on either
 * the resume or the transcript side to extend. Driven off the backend's
 * precomputed boolean rather than re-deriving catalog_course_id IS NULL here,
 * so the client cannot disagree with the server about what counts as matched.
 */
function CourseFlags({ row }: { row: TranscriptRecord }) {
  const flags: string[] = [];
  if (row.needs_catalog_review) flags.push('No catalog match — check the course code');
  if (!row.counts_toward_gpa) flags.push('Does not count toward GPA');
  // Carried over from the previous card's meta row. Not a warning, but worth
  // stating: transcript imports default every course to resident credit, and
  // transfer/dual-enrollment are not detected yet, so a student checking their
  // record needs to see what was assumed.
  flags.push(
    row.credit_type === 'resident'
      ? 'Resident (default)'
      : row.credit_type.replace('_', ' '),
  );
  if (flags.length === 0) return null;

  return (
    <ul
      className="rv-card-flags"
      {...(row.needs_catalog_review ? { 'data-catalog-check': row.id } : {})}
    >
      {flags.map((flag) => (
        <li key={flag} className="rv-card-flag">
          {flag}
        </li>
      ))}
    </ul>
  );
}
