import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import {
  CERT_STATUS_VALUES,
  GLYPH_EDITED,
  formatListInput,
  formatNumberInput,
  parseListInput,
  parseNumberInput,
} from '../../lib/resumeApi.mjs';
import type { ReviewField } from '../../lib/resumeApi.mjs';

/**
 * Input types whose selection API is defined (HTML spec: text, search, url,
 * tel, password). Every other type -- number among them -- throws on
 * setSelectionRange rather than ignoring it.
 */
const SELECTABLE_INPUT_TYPES = new Set(['text', 'search', 'url', 'tel', 'password']);

function isSelectableInput(node: Element): node is HTMLInputElement {
  return node instanceof HTMLInputElement && SELECTABLE_INPUT_TYPES.has(node.type);
}

export interface FieldRowProps {
  field: ReviewField;
  idPrefix: string;
  /** The glyph for this row, from fieldGlyph(). */
  glyph: string | null;
  value: unknown;
  /** already_confirmed rows render as plain text with no glyph and no editing. */
  locked: boolean;
  /** Open in edit mode on mount -- used when a gap pill is promoted to a row. */
  autoEdit?: boolean;
  onChange(next: unknown): void;
  /**
   * Commit through the existing draft/PATCH path. Resolves to whether a save
   * actually round-tripped, which is what gates the confirmation flash.
   */
  onCommit(overrides?: Record<string, unknown>): Promise<boolean> | boolean;
}

/**
 * One field of one entry: glyph gutter, label, and a value that becomes an
 * input in place when clicked.
 *
 * WHY THE READ VIEW IS A <button>: it has to be reachable by keyboard and
 * operable with Enter/Space. A div with onClick is neither, and this is the
 * only way into editing anything on the screen -- making it mouse-only would
 * put the entire review flow out of reach for keyboard and screen-reader users.
 *
 * WHY THE SAVE FLASH AWAITS THE COMMIT: the flash is a save confirmation, not
 * decoration. Firing it optimistically on blur would show the same reassurance
 * for a save that succeeded and one that 409'd, which is worse than no signal
 * at all. It runs only after onCommit's promise resolves.
 */
export function FieldRow({
  field,
  idPrefix,
  glyph,
  value,
  locked,
  autoEdit = false,
  onChange,
  onCommit,
}: FieldRowProps) {
  const [editing, setEditing] = useState(autoEdit);
  const [flash, setFlash] = useState(false);
  const [text, setText] = useState(() => toText(field, value));
  // The value as it was when editing opened, so Escape can put it back.
  const escapeValueRef = useRef<unknown>(value);
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null>(null);
  const id = `${idPrefix}-${field.name}`;

  // Adopt an externally-changed value (the server's saved version, or a
  // revert) while not clobbering in-progress typing. Same guard the previous
  // ListFieldEditor used, generalized to every type.
  const [lastValue, setLastValue] = useState(value);
  if (value !== lastValue && !editing) {
    setLastValue(value);
    setText(toText(field, value));
  }

  useLayoutEffect(() => {
    if (!editing) return;
    const node = inputRef.current;
    if (!node) return;
    node.focus();
    // setSelectionRange is only defined for text-like inputs. Calling it on
    // <input type="number"> THROWS ("does not support selection"), which
    // unmounts the card mid-edit rather than degrading -- so the guard is on
    // the input's type, not just its element class. Textareas always support
    // it. Caret placement is a nicety; the focus above is the part that
    // matters, and it still happens for every type.
    if (node instanceof HTMLTextAreaElement || isSelectableInput(node)) {
      const end = node.value.length;
      node.setSelectionRange(end, end);
    }
  }, [editing]);

  useEffect(() => {
    if (!flash) return;
    const timer = window.setTimeout(() => setFlash(false), 900);
    return () => window.clearTimeout(timer);
  }, [flash]);

  function openEditor() {
    if (locked) return;
    escapeValueRef.current = value;
    setText(toText(field, value));
    setEditing(true);
  }

  async function closeAndSave() {
    setEditing(false);
    const parsed = fromText(field, text, escapeValueRef.current);
    onChange(parsed);
    // Only flash when a save actually landed. A no-op blur (nothing changed) and
    // a rejected edit (409, conflict) both resolve false and must not show the
    // same reassurance as a success.
    const saved = await onCommit({ [field.name]: parsed });
    if (saved) setFlash(true);
  }

  function cancel() {
    setEditing(false);
    setText(toText(field, escapeValueRef.current));
    onChange(escapeValueRef.current);
  }

  const rowClass = ['rv-field', flash ? 'rv-field-flash' : ''].filter(Boolean).join(' ');

  // Locked rows are plain text: no glyph, no button, nothing focusable. The
  // already_confirmed state means the server rejected the edit, so offering an
  // editor would invite a change that cannot land.
  if (locked) {
    return (
      <div className="rv-field rv-field-locked">
        <span className="rv-glyph" aria-hidden="true" />
        <span className="rv-field-label">{field.label}</span>
        <span className="rv-field-value">{renderRead(field, value)}</span>
      </div>
    );
  }

  if (editing) {
    return (
      <div className={rowClass}>
        <span className="rv-glyph" aria-hidden="true">
          {glyph}
        </span>
        <label className="rv-field-label" htmlFor={id}>
          {field.label}
        </label>
        <span className="rv-field-value">
          {renderEditor({ field, id, text, setText, inputRef, closeAndSave, cancel })}
        </span>
      </div>
    );
  }

  return (
    <div className={rowClass}>
      <span
        className={glyph === GLYPH_EDITED ? 'rv-glyph rv-glyph-edited' : 'rv-glyph'}
        aria-hidden="true"
      >
        {glyph}
      </span>
      <span className="rv-field-label" id={`${id}-label`}>
        {field.label}
      </span>
      <button
        type="button"
        className="rv-field-value rv-field-button"
        aria-labelledby={`${id}-label`}
        onClick={openEditor}
      >
        {renderRead(field, value)}
      </button>
    </div>
  );
}

// ── value <-> text ──────────────────────────────────────────────────────────

function toText(field: ReviewField, value: unknown): string {
  if (field.type === 'list') return formatListInput(value);
  if (field.type === 'number') return formatNumberInput(value);
  return typeof value === 'string' ? value : '';
}

/**
 * Parse edited text back to a stored value.
 *
 * `previous` is the pre-edit value and is the fallback for a `number` that will
 * not parse: rejecting garbage by reverting is the spec's requirement, and it
 * is also the only safe choice for a field that feeds arithmetic -- accepting
 * "3 hours" as 3 would be a silently wrong number.
 */
function fromText(field: ReviewField, text: string, previous: unknown): unknown {
  if (field.type === 'list') return parseListInput(text);
  if (field.type === 'number') {
    const trimmed = text.trim();
    if (trimmed === '') return null;
    const parsed = parseNumberInput(trimmed);
    return parsed === null ? previous : parsed;
  }
  const trimmed = text.trim();
  return trimmed === '' ? null : trimmed;
}

// ── read view ───────────────────────────────────────────────────────────────

function renderRead(field: ReviewField, value: unknown) {
  if (field.type === 'list') {
    const items = Array.isArray(value) ? value : [];
    if (items.length === 0) return <span className="rv-empty">—</span>;
    return (
      <span className="rv-chips">
        {items.map((item, index) => (
          <span className="rv-chip" key={`${String(item)}-${String(index)}`}>
            {String(item)}
          </span>
        ))}
        <span className="rv-chip-count">{items.length}</span>
      </span>
    );
  }

  if (field.type === 'status') {
    if (value === 'completed') return 'Completed';
    if (value === 'in_progress') return 'In progress';
    return <span className="rv-empty">—</span>;
  }

  if (field.type === 'number') {
    const shown = formatNumberInput(value);
    return shown === '' ? <span className="rv-empty">—</span> : shown;
  }

  const text = typeof value === 'string' ? value : '';
  if (!text.trim()) return <span className="rv-empty">—</span>;
  // textarea values render in full, wrapped. Never truncated or scroll-clipped:
  // a description the student cannot read in full is one they cannot check.
  return <span className={field.type === 'textarea' ? 'rv-longtext' : undefined}>{text}</span>;
}

// ── edit view ───────────────────────────────────────────────────────────────

interface EditorArgs {
  field: ReviewField;
  id: string;
  text: string;
  setText(next: string): void;
  inputRef: React.MutableRefObject<
    HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null
  >;
  closeAndSave(): void | Promise<void>;
  cancel(): void;
}

function renderEditor({ field, id, text, setText, inputRef, closeAndSave, cancel }: EditorArgs) {
  const commit = () => {
    void closeAndSave();
  };

  // Enter saves single-line fields; Escape always reverts. A textarea keeps
  // Enter for newlines -- blur is its save.
  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      cancel();
      return;
    }
    if (event.key === 'Enter' && field.type !== 'textarea') {
      event.preventDefault();
      (event.currentTarget as HTMLElement).blur();
    }
  };

  if (field.type === 'textarea') {
    return (
      <textarea
        id={id}
        ref={(node) => {
          inputRef.current = node;
        }}
        className="rv-input rv-input-area"
        value={text}
        rows={Math.max(2, Math.min(14, text.split('\n').length + 1))}
        onChange={(event) => setText(event.target.value)}
        onBlur={commit}
        onKeyDown={onKeyDown}
      />
    );
  }

  if (field.type === 'status') {
    return (
      <select
        id={id}
        ref={(node) => {
          inputRef.current = node;
        }}
        className="rv-input"
        value={text}
        onChange={(event) => setText(event.target.value)}
        onBlur={commit}
        onKeyDown={onKeyDown}
      >
        <option value="">Not stated</option>
        {CERT_STATUS_VALUES.map((status) => (
          <option key={status} value={status}>
            {status === 'completed' ? 'Completed' : 'In progress'}
          </option>
        ))}
      </select>
    );
  }

  return (
    <input
      id={id}
      ref={(node) => {
        inputRef.current = node;
      }}
      className="rv-input"
      type={field.type === 'number' ? 'number' : 'text'}
      inputMode={field.type === 'number' ? 'decimal' : undefined}
      step={field.type === 'number' ? 'any' : undefined}
      value={text}
      placeholder={field.type === 'list' ? `Comma separated ${field.label.toLowerCase()}…` : undefined}
      onChange={(event) => setText(event.target.value)}
      onBlur={commit}
      onKeyDown={onKeyDown}
    />
  );
}
