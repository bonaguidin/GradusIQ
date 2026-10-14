import { useEffect, useId, useRef, useState } from 'react';
import type { ClipboardEvent as ReactClipboardEvent, DragEvent, FormEvent } from 'react';
import { useFocusTrap } from '../hooks/useFocusTrap';
import { sendReport } from '../api/reportIssue';
import {
  REPORT_KINDS,
  REPORT_LIMITS,
  fitWithin,
  screenshotFits,
  validateReport,
} from '../lib/reportIssue.mjs';
import type { ReportKind } from '../lib/reportIssue.mjs';
import './ReportIssueDialog.css';

interface Attachment {
  id: number;
  blob: Blob;
  name: string;
  url: string;
}

const ACCEPTED_TYPES = ['image/png', 'image/jpeg', 'image/webp'];

/**
 * Shrinks a screenshot before upload. A full-resolution retina capture can be
 * 5 MB+, and Vercel refuses any request body over 4.5 MB, so anything larger
 * than 1600px on its longest side or over the per-image cap is redrawn and
 * re-encoded as JPEG. Small PNGs are kept as they are: text in a PNG stays
 * sharper than in a JPEG.
 */
async function prepareImage(file: Blob, index: number): Promise<{ blob: Blob; name: string }> {
  const bitmap = await createImageBitmap(file);
  try {
    const target = fitWithin(bitmap.width, bitmap.height);
    const alreadySmall =
      target.width === bitmap.width &&
      file.size <= REPORT_LIMITS.maxScreenshotBytes &&
      (file.type === 'image/png' || file.type === 'image/jpeg' || file.type === 'image/webp');
    if (alreadySmall) {
      const ext = file.type === 'image/png' ? 'png' : file.type === 'image/webp' ? 'webp' : 'jpg';
      return { blob: file, name: `screenshot-${index}.${ext}` };
    }
    const canvas = document.createElement('canvas');
    canvas.width = target.width;
    canvas.height = target.height;
    const context = canvas.getContext('2d');
    if (!context) throw new Error('canvas');
    // JPEG has no transparency; paint white first so a transparent PNG
    // doesn't come out black.
    context.fillStyle = '#FFFFFF';
    context.fillRect(0, 0, target.width, target.height);
    context.drawImage(bitmap, 0, 0, target.width, target.height);
    for (const quality of [0.85, 0.7, 0.55]) {
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality));
      if (blob && blob.size <= REPORT_LIMITS.maxScreenshotBytes) {
        return { blob, name: `screenshot-${index}.jpg` };
      }
    }
    throw new Error('too-large');
  } finally {
    bitmap.close();
  }
}

const FIT_MESSAGES = {
  count: `You can attach up to ${REPORT_LIMITS.maxScreenshots} screenshots.`,
  size: 'That image is too large, even after shrinking it.',
  total: 'Those screenshots are too large together. Remove one first.',
} as const;

/**
 * The bug / feature report pop-up behind the topbar bug icon.
 *
 * Same dialog pattern as EditCoursesDialog and GuidedTour: role="dialog" +
 * aria-modal, focus moved in on open, Tab trapped (useFocusTrap), Escape to
 * close. The caller (ReportIssueButton) returns focus to the trigger.
 *
 * The send button is a plain .btn-primary with a "Sending…" label, not the
 * ConfirmButton animation: a report doesn't change the student's record, and
 * the animation is kept for the moments that do. Success swaps the form for
 * a thank-you panel instead.
 */
export function ReportIssueDialog({
  accessToken,
  defaultName,
  defaultEmail,
  pageLabel,
  onClose,
}: {
  accessToken: string | null;
  defaultName: string;
  defaultEmail: string;
  /** Where the student was when they opened it, e.g. "Overview". */
  pageLabel: string;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const nextId = useRef(1);
  const titleId = useId();
  const descriptionId = useId();

  const [kind, setKind] = useState<ReportKind>('bug');
  const [description, setDescription] = useState('');
  const [name, setName] = useState(defaultName);
  const [email, setEmail] = useState(defaultEmail);
  const [website, setWebsite] = useState('');
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [attachError, setAttachError] = useState<string | null>(null);
  const [processing, setProcessing] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<{ description?: string; email?: string }>({});
  const [sendError, setSendError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);

  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  useFocusTrap(dialogRef);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  // Object URLs back the thumbnails; release them all when the dialog goes.
  const attachmentsRef = useRef(attachments);
  attachmentsRef.current = attachments;
  useEffect(() => () => attachmentsRef.current.forEach((a) => URL.revokeObjectURL(a.url)), []);

  async function addFiles(files: Blob[]) {
    setAttachError(null);
    const images = files.filter((file) => ACCEPTED_TYPES.includes(file.type));
    if (images.length === 0) {
      if (files.length > 0) setAttachError('Screenshots need to be PNG, JPEG or WebP images.');
      return;
    }
    setProcessing(true);
    try {
      let current = attachmentsRef.current;
      for (const file of images) {
        const id = nextId.current++;
        let prepared: { blob: Blob; name: string };
        try {
          prepared = await prepareImage(file, id);
        } catch {
          setAttachError(FIT_MESSAGES.size);
          continue;
        }
        const fit = screenshotFits(current.map((a) => a.blob.size), prepared.blob.size);
        if (fit !== 'ok') {
          setAttachError(FIT_MESSAGES[fit]);
          break;
        }
        const attachment = { id, ...prepared, url: URL.createObjectURL(prepared.blob) };
        current = [...current, attachment];
        setAttachments(current);
      }
    } finally {
      setProcessing(false);
    }
  }

  function removeAttachment(id: number) {
    setAttachError(null);
    setAttachments((prev) => {
      const gone = prev.find((a) => a.id === id);
      if (gone) URL.revokeObjectURL(gone.url);
      return prev.filter((a) => a.id !== id);
    });
  }

  function onPaste(event: ReactClipboardEvent<HTMLDivElement>) {
    const files = Array.from(event.clipboardData.files);
    if (files.some((file) => file.type.startsWith('image/'))) {
      event.preventDefault();
      void addFiles(files);
    }
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    void addFiles(Array.from(event.dataTransfer.files));
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSendError(null);
    const errors = validateReport({ description, email });
    setFieldErrors(errors);
    if (errors.description || errors.email) return;

    setSending(true);
    const result = await sendReport(
      accessToken,
      {
        kind,
        description,
        email,
        name,
        page: `${pageLabel} (${window.location.pathname})`,
        userAgent: navigator.userAgent,
        website,
      },
      attachments.map(({ blob, name: fileName }) => ({ blob, name: fileName })),
    );
    setSending(false);
    if (result.ok) {
      setSent(true);
    } else {
      setSendError(result.message);
    }
  }

  const isBug = kind === 'bug';
  const full = attachments.length >= REPORT_LIMITS.maxScreenshots;

  return (
    <div
      className="report-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        className="report-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        tabIndex={-1}
        onPaste={sent ? undefined : onPaste}
      >
        <header className="report-header">
          <div>
            <p className="report-eyebrow">Feedback</p>
            <h2 id={titleId} className="report-title">
              {sent ? 'Thanks, it’s on its way' : 'Report a bug or suggest a feature'}
            </h2>
            <p id={descriptionId} className="report-subtitle">
              {sent
                ? `The GradusIQ team reads every report. If we need more detail, we’ll email ${email.trim()}.`
                : 'This goes straight to the GradusIQ team, and we reply by email.'}
            </p>
          </div>
          <button type="button" className="report-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>

        {sent ? (
          <div className="report-sent">
            <span className="report-sent-mark" aria-hidden="true">
              <svg viewBox="0 0 24 24"><path d="M5 13l4 4L19 7" /></svg>
            </span>
            <div className="report-footer">
              <button type="button" className="btn btn-primary" onClick={onClose}>Done</button>
            </div>
          </div>
        ) : (
          <form className="report-form" onSubmit={(event) => { void onSubmit(event); }} noValidate>
            <div className="report-kind" role="radiogroup" aria-label="Report type">
              {REPORT_KINDS.map((option) => (
                <label
                  key={option.value}
                  className={`report-kind-option${kind === option.value ? ' is-selected' : ''}`}
                >
                  <input
                    type="radio"
                    name="report-kind"
                    value={option.value}
                    checked={kind === option.value}
                    onChange={() => setKind(option.value)}
                  />
                  <span className="report-kind-icon" aria-hidden="true">
                    {option.value === 'bug' ? <BugIcon /> : <IdeaIcon />}
                  </span>
                  {option.label}
                </label>
              ))}
            </div>

            <label className="report-field">
              <span className="report-label">{isBug ? 'What happened?' : 'What would you like to see?'}</span>
              <textarea
                className="form-textarea report-textarea"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                maxLength={REPORT_LIMITS.maxDescription}
                rows={5}
                placeholder={
                  isBug
                    ? 'What were you doing, what did you expect, and what happened instead?'
                    : 'Describe the idea and the problem it would solve for you.'
                }
                aria-invalid={fieldErrors.description ? true : undefined}
                aria-describedby={fieldErrors.description ? 'report-description-error' : undefined}
              />
              {fieldErrors.description && (
                <span id="report-description-error" className="report-field-error">{fieldErrors.description}</span>
              )}
            </label>

            <div className="report-field">
              <span className="report-label">
                Screenshots <span className="report-optional">optional, up to {REPORT_LIMITS.maxScreenshots}</span>
              </span>
              <div
                className={`report-drop${dragging ? ' is-dragging' : ''}${full ? ' is-full' : ''}`}
                onDragOver={(event) => { event.preventDefault(); if (!full) setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={onDrop}
              >
                {attachments.map((attachment, index) => (
                  <figure key={attachment.id} className="report-thumb">
                    <img src={attachment.url} alt={`Screenshot ${index + 1}`} />
                    <button
                      type="button"
                      className="report-thumb-remove"
                      onClick={() => removeAttachment(attachment.id)}
                      aria-label={`Remove screenshot ${index + 1}`}
                    >
                      ×
                    </button>
                  </figure>
                ))}
                {!full && (
                  <button
                    type="button"
                    className="report-drop-add"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={processing}
                  >
                    <span className="report-drop-plus" aria-hidden="true">+</span>
                    <span>{processing ? 'Adding…' : attachments.length ? 'Add another' : 'Drop, paste or browse'}</span>
                  </button>
                )}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept={ACCEPTED_TYPES.join(',')}
                  multiple
                  hidden
                  onChange={(event) => {
                    const files = Array.from(event.target.files ?? []);
                    event.target.value = '';
                    void addFiles(files);
                  }}
                />
              </div>
              {attachError && <span className="report-field-error" role="alert">{attachError}</span>}
            </div>

            <div className="report-contact">
              <label className="report-field">
                <span className="report-label">Name <span className="report-optional">optional</span></span>
                <input
                  className="form-input"
                  type="text"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  autoComplete="name"
                  maxLength={120}
                />
              </label>
              <label className="report-field">
                <span className="report-label">Email</span>
                <input
                  className="form-input"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  autoComplete="email"
                  maxLength={254}
                  aria-invalid={fieldErrors.email ? true : undefined}
                  aria-describedby={fieldErrors.email ? 'report-email-error' : undefined}
                />
                {fieldErrors.email && (
                  <span id="report-email-error" className="report-field-error">{fieldErrors.email}</span>
                )}
              </label>
            </div>

            {/* Honeypot. Hidden from people and screen readers; a bot that
                fills every field fills this one too, and the backend drops
                the report without telling it. */}
            <div className="report-honeypot" aria-hidden="true">
              <label>
                Website
                <input
                  type="text"
                  name="website"
                  tabIndex={-1}
                  autoComplete="off"
                  value={website}
                  onChange={(event) => setWebsite(event.target.value)}
                />
              </label>
            </div>

            {sendError && <p className="report-send-error" role="alert">{sendError}</p>}

            <div className="report-footer">
              <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={sending || processing}
                aria-busy={sending || undefined}
              >
                {sending ? 'Sending…' : 'Send report'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

export function BugIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 7.5V6a3 3 0 0 1 6 0v1.5" />
      <rect x="7" y="7.5" width="10" height="12" rx="5" />
      <path d="M12 11v8.5M7 12H4M20 12h-3M7 16.5H4.5M19.5 16.5H17M8 9L5.5 7M16 9l2.5-2" />
    </svg>
  );
}

function IdeaIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 18h6M10 21h4" />
      <path d="M12 3a6 6 0 0 0-3.5 10.9c.6.4 1 1.1 1 1.8V16h5v-.3c0-.7.4-1.4 1-1.8A6 6 0 0 0 12 3z" />
    </svg>
  );
}
