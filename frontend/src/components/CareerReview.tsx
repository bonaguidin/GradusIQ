import { useCallback, useEffect, useMemo, useState } from 'react';
import { confirmCareerRecords, fetchCareerReview, patchCareerRow } from '../api/resume';
import {
  CHILD_TABLES,
  REVIEW_SECTIONS,
  changedFields,
  reviewCounters,
} from '../lib/resumeApi.mjs';
import type {
  CounterRow,
  NormalizedConfirm,
  ResumeAcademicFacts,
  ReviewRow,
  ReviewSections,
  SectionKey,
} from '../lib/resumeApi.mjs';
import { CommitBar } from './review/CommitBar';
import { EntryCard } from './review/EntryCard';
import { LedgerBar } from './review/LedgerBar';

interface CareerReviewProps {
  accessToken: string;
  onConfirmed(result: NormalizedConfirm): void;
  /** Successful page-load recovery can hydrate the review without a second GET. */
  initialSections?: ReviewSections;
  /**
   * Masthead provenance. Both optional and both purely presentational -- the
   * screen works without them, so a caller that does not have the filename (a
   * direct link into review, say) degrades to omitting the line rather than
   * rendering "undefined".
   */
  sourceName?: string;
  parsedAt?: Date;
  academicFacts?: ResumeAcademicFacts;
}

/** Per-row UI state: an inline message, and whether editing is still allowed. */
interface RowState {
  message: string | null;
  tone: 'error' | 'saved';
  locked: boolean;
}

type RowStates = Record<string, RowState>;

const EMPTY_SECTIONS: ReviewSections = {
  career_profile: null,
  certifications: [],
  work_experience: [],
  projects: [],
};

function rowKey(table: SectionKey, id: string) {
  return `${table}:${id}`;
}

function draftsFromSections(sections: ReviewSections): Record<string, ReviewRow> {
  const rows: Record<string, ReviewRow> = {};
  if (sections.career_profile) {
    rows[rowKey('career_profile', sections.career_profile.id)] = { ...sections.career_profile };
  }
  for (const table of CHILD_TABLES) {
    for (const row of sections[table]) rows[rowKey(table, row.id)] = { ...row };
  }
  return rows;
}

function cloneRows(rows: Record<string, ReviewRow>): Record<string, ReviewRow> {
  return Object.fromEntries(Object.entries(rows).map(([key, row]) => [key, { ...row }]));
}

const DATE_FMT = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: 'short',
  day: '2-digit',
});

export function CareerReview({
  accessToken,
  onConfirmed,
  initialSections,
  sourceName,
  parsedAt,
  academicFacts,
}: CareerReviewProps) {
  const initialRows = useMemo(
    () => (initialSections ? draftsFromSections(initialSections) : {}),
    [initialSections],
  );
  const [sections, setSections] = useState<ReviewSections>(initialSections ?? EMPTY_SECTIONS);
  const [drafts, setDrafts] = useState<Record<string, ReviewRow>>(initialRows);
  /**
   * The rows EXACTLY as first loaded -- what the resume parse produced.
   *
   * Glyphs and the "edited by you" counter compare against this, never against
   * `sections`. `sections` is replaced by the server's saved row after every
   * PATCH, so diffing against it would erase the edit marker the instant the
   * edit succeeded, and the counter would sit at 0 no matter how much the
   * student corrected. Provenance is a fact about where a value came from, not
   * about whether it currently differs from the server.
   *
   * `commit` still diffs against `sections` -- what to PATCH is a different
   * question from what to mark, and sending fields that already match the
   * server would be wrong.
   */
  const [baseline, setBaseline] = useState<Record<string, ReviewRow>>(() => cloneRows(initialRows));
  const [rowStates, setRowStates] = useState<RowStates>({});
  const [loading, setLoading] = useState(initialSections === undefined);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [justSaved, setJustSaved] = useState(false);
  const [academicDraft, setAcademicDraft] = useState<ResumeAcademicFacts>(
    academicFacts ?? { major_current: null, expected_graduation: null },
  );

  useEffect(() => {
    if (initialSections) {
      const recovered = draftsFromSections(initialSections);
      setSections(initialSections);
      setDrafts(recovered);
      setBaseline(cloneRows(recovered));
      setLoadError(null);
      setLoading(false);
      return;
    }

    let active = true;
    void (async () => {
      const result = await fetchCareerReview(accessToken);
      if (!active) return;
      if (result.ok) {
        setSections(result.sections);
        const initial = draftsFromSections(result.sections);
        setDrafts(initial);
        setBaseline(cloneRows(initial));
      } else {
        setLoadError(result.message);
      }
      setLoading(false);
    })();
    return () => {
      active = false;
    };
  }, [accessToken, initialSections]);

  const setRowState = useCallback((key: string, state: RowState | null) => {
    setRowStates((prev) => {
      const next = { ...prev };
      if (state === null) delete next[key];
      else next[key] = state;
      return next;
    });
  }, []);

  const removeRow = useCallback((table: SectionKey, id: string) => {
    setSections((prev) => {
      if (table === 'career_profile') return { ...prev, career_profile: null };
      return { ...prev, [table]: prev[table].filter((row) => row.id !== id) };
    });
    setDrafts((prev) => {
      const next = { ...prev };
      delete next[rowKey(table, id)];
      return next;
    });
    setBaseline((prev) => {
      const next = { ...prev };
      delete next[rowKey(table, id)];
      return next;
    });
  }, []);

  /**
   * Save one row's changes. UNCHANGED from the previous implementation except
   * for the return value: it now resolves to whether a save actually
   * round-tripped, so FieldRow's confirmation flash fires only for a real save
   * and not for a no-op blur or a rejected edit.
   */
  const commit = useCallback(
    async (
      table: SectionKey,
      original: ReviewRow,
      overrides?: Record<string, unknown>,
    ): Promise<boolean> => {
      const key = rowKey(table, original.id);
      const stored = drafts[key];
      if (!stored) return false;
      const draft = overrides ? { ...stored, ...overrides } : stored;

      const changes = changedFields(table, original, draft);
      if (Object.keys(changes).length === 0) return false;

      const result = await patchCareerRow(accessToken, table, original.id, changes);

      if (result.ok && result.row) {
        // Adopt the server's version, not the draft: it reflects any
        // normalization the backend applied (status lower-cased, blanks nulled).
        const saved = result.row;
        setSections((prev) => {
          if (table === 'career_profile') return { ...prev, career_profile: saved };
          return {
            ...prev,
            [table]: prev[table].map((row) => (row.id === saved.id ? saved : row)),
          };
        });
        setDrafts((prev) => ({ ...prev, [key]: { ...saved } }));
        setRowState(key, null);
        return true;
      }

      if (result.kind === 'not_found') {
        // Gone, for a reason the backend deliberately will not disclose.
        removeRow(table, original.id);
        setRowState(key, null);
        return false;
      }

      if (result.kind === 'already_confirmed') {
        // Lock it and restore the stored values -- the edit did not apply.
        setDrafts((prev) => ({ ...prev, [key]: { ...original } }));
        setRowState(key, { message: result.message, tone: 'error', locked: true });
        return false;
      }

      // conflict | invalid | anything else: keep what they typed so it can be
      // corrected, but make clear it is not saved.
      setRowState(key, { message: result.message, tone: 'error', locked: false });
      return false;
    },
    [accessToken, drafts, removeRow, setRowState],
  );

  function updateDraft(key: string, fieldName: string, value: unknown) {
    setDrafts((prev) => ({ ...prev, [key]: { ...prev[key], [fieldName]: value } }));
  }

  async function handleConfirm() {
    setConfirming(true);
    setConfirmError(null);
    const result = await confirmCareerRecords(accessToken, academicDraft);
    if (result.ok) {
      // Brief acknowledgement before the page machine advances, so the click
      // visibly did something rather than the screen simply vanishing.
      setJustSaved(true);
      // `confirming` stays true on success on purpose -- see TranscriptReview's
      // handleConfirm for the reasoning. It clears when this screen unmounts.
      //
      // 650ms, not 450: CommitBar's success state (the button's own slam +
      // ring) runs up to 600ms, and the point of adding it was for the
      // student to actually see it before the screen moves on.
      window.setTimeout(() => onConfirmed(result), 650);
      return;
    }
    // API failure, timeout and validation all land here: the screen stays put
    // and remains retryable.
    setConfirmError(result.message);
    setConfirming(false);
  }

  /** Every rendered row, paired with its server original, for the counters. */
  const counterRows: CounterRow[] = useMemo(() => {
    const rows: CounterRow[] = [];
    if (sections.career_profile) {
      const key = rowKey('career_profile', sections.career_profile.id);
      rows.push({
        table: 'career_profile',
        original: baseline[key] ?? sections.career_profile,
        draft: drafts[key] ?? sections.career_profile,
      });
    }
    for (const table of CHILD_TABLES) {
      for (const row of sections[table]) {
        const key = rowKey(table, row.id);
        rows.push({ table, original: baseline[key] ?? row, draft: drafts[key] ?? row });
      }
    }
    return rows;
  }, [sections, drafts, baseline]);

  const counters = useMemo(() => reviewCounters(counterRows), [counterRows]);

  /**
   * Scroll to the first unfilled field on the page, flag it, then focus it.
   *
   * Queries the DOM rather than tracking gap positions in state: document order
   * is exactly the ordering wanted, and the DOM is the only place it already
   * exists. Focus happens after the scroll so the browser does not fight its
   * own smooth scroll with a focus-induced jump.
   */
  const jumpToGap = useCallback(() => {
    const pill = document.querySelector<HTMLButtonElement>('[data-gap-pill]');
    if (!pill) return;
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    pill.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'center' });
    pill.classList.add('rv-gap-pill-flag');
    window.setTimeout(() => pill.classList.remove('rv-gap-pill-flag'), 500);
    window.setTimeout(() => pill.focus(), reduce ? 0 : 320);
  }, []);

  if (loading) {
    return (
      <div className="loading-screen">
        <div className="spinner" role="status" aria-label="Loading your records" />
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="login-bg">
        <div className="login-card">
          <div className="login-header">
            <h1 className="login-logo">GradusIQ</h1>
            <p className="login-subtitle">Could not load your records</p>
          </div>
          <div className="login-form">
            <p className="login-error" role="alert">
              {loadError}
            </p>
          </div>
        </div>
      </div>
    );
  }

  const hasProfile = sections.career_profile !== null;
  const hasAcademicFacts = Boolean(
    academicFacts?.major_current || academicFacts?.expected_graduation,
  );
  const pending =
    (hasProfile ? 1 : 0) +
    (hasAcademicFacts ? 1 : 0) +
    CHILD_TABLES.reduce((n, t) => n + sections[t].length, 0);

  if (pending === 0) {
    return (
      <div className="login-bg">
        <div className="login-card">
          <div className="login-header">
            <h1 className="login-logo">GradusIQ</h1>
            <p className="login-subtitle">Nothing to review</p>
          </div>
          <div className="login-form">
            <p className="resume-intro">
              There is nothing waiting for your review — everything from your resume has already
              been confirmed.
            </p>
          </div>
        </div>
      </div>
    );
  }

  function renderCard(table: SectionKey, row: ReviewRow, index: number) {
    const key = rowKey(table, row.id);
    const draft = drafts[key] ?? row;
    const state = rowStates[key];
    return (
      <EntryCard
        key={key}
        table={table}
        // Glyph provenance compares to the resume-parsed baseline; the commit
        // closure below still diffs against `row`, the live server version.
        original={baseline[key] ?? row}
        draft={draft}
        index={index}
        locked={state?.locked ?? false}
        message={state?.message ?? null}
        tone={state?.tone ?? 'saved'}
        onChange={(fieldName, next) => updateDraft(key, fieldName, next)}
        onCommit={(overrides) => commit(table, row, overrides)}
      />
    );
  }

  return (
    <div className="rv-bg">
      <div className="rv-page">
        <header className="rv-masthead">
          <div className="rv-masthead-top">
            <span className="rv-wordmark">GradusIQ</span>
            {(sourceName || parsedAt) && (
              <span className="rv-provenance">
                {sourceName && <span className="rv-provenance-file">{sourceName}</span>}
                {parsedAt && <span>read {DATE_FMT.format(parsedAt)}</span>}
              </span>
            )}
          </div>
          <h1 className="rv-headline">Here&rsquo;s what we read.</h1>
          <p className="rv-standfirst">
            Every line below came off your resume and none of it is saved yet. A{' '}
            <span className="rv-inline-glyph">·</span> means we read it as-is, a{' '}
            <span className="rv-inline-glyph rv-glyph-edited">✎</span> means you changed it. Click
            anything to correct it — edits save as you go.
          </p>
        </header>

        <LedgerBar counters={counters} onJumpToGap={jumpToGap} />

        {hasAcademicFacts && (
          <section className="rv-section">
            <h2 className="rv-section-head">
              Academic facts
              <span className="rv-section-count">1</span>
            </h2>
            <article className="rv-card">
              <header className="rv-card-head">
                <h3 className="rv-card-title">Education</h3>
              </header>
              <div className="rv-card-fields">
                {academicFacts?.major_current && (
                  <label className="form-group">
                    <span className="form-label">Current major</span>
                    <input
                      className="form-input"
                      name="academic-major-current"
                      value={academicDraft.major_current ?? ''}
                      onChange={(event) =>
                        setAcademicDraft((current) => ({
                          ...current,
                          major_current: event.target.value || null,
                        }))
                      }
                      autoComplete="off"
                    />
                  </label>
                )}
                {academicFacts?.expected_graduation && (
                  <label className="form-group">
                    <span className="form-label">Expected graduation</span>
                    <input
                      className="form-input"
                      name="academic-expected-graduation"
                      value={academicDraft.expected_graduation ?? ''}
                      onChange={(event) =>
                        setAcademicDraft((current) => ({
                          ...current,
                          expected_graduation: event.target.value || null,
                        }))
                      }
                      autoComplete="off"
                    />
                    <small>Use Spring YYYY or Fall YYYY.</small>
                  </label>
                )}
              </div>
            </article>
          </section>
        )}

        {hasProfile && sections.career_profile && (
          <section className="rv-section">
            <h2 className="rv-section-head">
              {REVIEW_SECTIONS.career_profile.label}
              <span className="rv-section-count">1</span>
            </h2>
            {renderCard('career_profile', sections.career_profile, 0)}
          </section>
        )}

        {CHILD_TABLES.map((table) =>
          sections[table].length === 0 ? null : (
            <section className="rv-section" key={table}>
              <h2 className="rv-section-head">
                {REVIEW_SECTIONS[table].label}
                <span className="rv-section-count">{sections[table].length}</span>
              </h2>
              {sections[table].map((row, index) => renderCard(table, row, index))}
            </section>
          ),
        )}
      </div>

      <CommitBar
        counters={counters}
        confirming={confirming}
        justSaved={justSaved}
        error={confirmError}
        onConfirm={() => {
          void handleConfirm();
        }}
      />
    </div>
  );
}
