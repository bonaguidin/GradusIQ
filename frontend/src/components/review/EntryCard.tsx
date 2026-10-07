import type { ReactNode } from 'react';
import { useState } from 'react';
import { REVIEW_SECTIONS, fieldGlyph, isEmptyValue } from '../../lib/resumeApi.mjs';
import type { ReviewField, ReviewRow, ReviewSection, SectionKey } from '../../lib/resumeApi.mjs';
import { FieldRow } from './FieldRow';
import { GapPills } from './GapPills';

export interface EntryCardProps {
  /** Identity for DOM ids. A SectionKey for resume; any key for another surface. */
  table: SectionKey | string;
  original: ReviewRow;
  draft: ReviewRow;
  index: number;
  locked: boolean;
  message: string | null;
  tone: 'error' | 'saved';
  onChange(fieldName: string, next: unknown): void;
  /** Resolves to whether a save round-tripped; gates FieldRow's confirmation flash. */
  onCommit(overrides?: Record<string, unknown>): Promise<boolean> | boolean;
  /**
   * The field config to render. Defaults to REVIEW_SECTIONS[table], so every
   * existing resume call site is unchanged. Transcript passes its own parallel
   * section rather than being registered in the career table map -- see
   * TRANSCRIPT_SECTION for why the registries stay separate.
   */
  section?: ReviewSection;
  /**
   * Provenance glyph for one field. Defaults to the shared fieldGlyph.
   * Transcript overrides it because credit_hours arrives as a string and is
   * edited as a number, so a raw === comparison would report a pure reformat
   * as an edit.
   */
  glyphFor?(original: ReviewRow, draft: ReviewRow, fieldName: string): string | null;
  /**
   * Card-level annotations (catalog review, repeat exclusion). Rendered under
   * the header. Resume passes nothing and is unaffected.
   */
  flags?: ReactNode;
  /** Suppresses the gap-pill row for surfaces where every field is expected. */
  hideGaps?: boolean;
}

/**
 * The card's serif headline: the section's title field, else a fallback.
 *
 * A section with NO titleField (career_profile, which is a singleton) gets the
 * section's own label rather than "career profile 1" -- numbering an entry that
 * can only ever be one of a kind reads like a bug. A section that HAS a
 * titleField but a blank value still numbers, because there really are others
 * to tell it apart from.
 */
function titleFor(section: ReviewSection, row: ReviewRow, index: number): string {
  const field = section.titleField;
  if (!field) return section.label;
  const value = row[field];
  if (typeof value === 'string' && value.trim()) return value.trim();
  return `${section.singular} ${String(index + 1)}`;
}

/**
 * The muted mono line under the title: up to two secondary values, whichever
 * of the section's non-title fields are filled, joined with a middot. Purely
 * derived -- no per-section subtitle config to drift out of sync with the
 * fields actually present.
 */
function subtitleFor(section: ReviewSection, row: ReviewRow): string {
  // An explicit list wins: the derived scan below picks the first two filled
  // non-title fields, which is right for a resume entry but would give a
  // course its own title back instead of the credits and grade that
  // distinguish it.
  if (section.subtitleFields) {
    const named: string[] = [];
    for (const name of section.subtitleFields) {
      const value = row[name];
      if (typeof value === 'string' && value.trim()) named.push(value.trim());
      else if (typeof value === 'number') named.push(String(value));
    }
    return named.join(' · ');
  }

  const parts: string[] = [];
  for (const field of section.fields) {
    if (field.name === section.titleField) continue;
    if (field.type === 'textarea' || field.type === 'list') continue;
    const value = row[field.name];
    if (typeof value === 'string' && value.trim()) {
      parts.push(value === 'in_progress' ? 'in progress' : value.trim());
    } else if (typeof value === 'number') {
      parts.push(String(value));
    }
    if (parts.length === 2) break;
  }
  return parts.join(' · ');
}

export function EntryCard({
  table,
  original,
  draft,
  index,
  locked,
  message,
  tone,
  onChange,
  onCommit,
  section: sectionProp,
  glyphFor = fieldGlyph,
  flags,
  hideGaps = false,
}: EntryCardProps) {
  // Fields promoted from a gap pill this session. They render as real rows even
  // while still empty, so the student can type into what they just clicked --
  // without this, an empty field would immediately collapse back into a pill.
  const [promoted, setPromoted] = useState<string[]>([]);
  const section = sectionProp ?? REVIEW_SECTIONS[table as SectionKey];
  const idPrefix = `${table}:${original.id}`;

  const shown: ReviewField[] = [];
  const gaps: ReviewField[] = [];
  for (const field of section.fields) {
    const filled = !isEmptyValue(draft[field.name]);
    if (filled || promoted.includes(field.name)) shown.push(field);
    else gaps.push(field);
  }

  return (
    <article
      className="rv-card rv-card-enter"
      // Capped so a long list's last few rows don't wait seconds to appear --
      // the cascade is for reading as "going through the list," not for
      // literally timing every row in it.
      style={{ animationDelay: `${Math.min(index, 10) * 45}ms` }}
    >
      <header className="rv-card-head">
        <h3 className="rv-card-title">{titleFor(section, draft, index)}</h3>
        {subtitleFor(section, draft) && (
          <p className="rv-card-sub">{subtitleFor(section, draft)}</p>
        )}
        {locked && <span className="rv-card-locked">confirmed · read only</span>}
      </header>

      {flags}

      <div className="rv-card-fields">
        {shown.map((field) => (
          <FieldRow
            key={field.name}
            field={field}
            idPrefix={idPrefix}
            glyph={glyphFor(original, draft, field.name)}
            value={draft[field.name]}
            locked={locked}
            autoEdit={promoted.includes(field.name) && isEmptyValue(draft[field.name])}
            onChange={(next) => onChange(field.name, next)}
            onCommit={onCommit}
          />
        ))}
      </div>

      {!locked && !hideGaps && (
        <GapPills
          fields={gaps}
          idPrefix={idPrefix}
          onPromote={(name) => setPromoted((prev) => (prev.includes(name) ? prev : [...prev, name]))}
        />
      )}

      {message && (
        <p
          className={tone === 'error' ? 'rv-card-error' : 'rv-card-saved'}
          role={tone === 'error' ? 'alert' : 'status'}
        >
          {message}
        </p>
      )}
    </article>
  );
}
