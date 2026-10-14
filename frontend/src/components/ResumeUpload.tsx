import { useRef, useState } from 'react';
import { uploadResume } from '../api/resume';
import { ConfirmButton, useConfirmStatus } from './ConfirmButton';
import { ProcessingStatus, processingLabel } from './ProcessingStatus';
import { RESUME_TRUST_NOTE } from '../lib/processingStages.mjs';
import type { NormalizedUpload } from '../lib/resumeApi.mjs';

interface ResumeUploadProps {
  accessToken: string;
  /** `fileName` is passed through to the review masthead as provenance. */
  onUploaded(result: NormalizedUpload, fileName: string): void;
}

const ACCEPTED = '.pdf,.docx';

/**
 * Kinds a different file will not fix -- offer "sign in again" or nothing,
 * rather than inviting the student to retry the same upload pointlessly.
 */
const NOT_RETRYABLE = new Set(['unauthenticated', 'no_student_profile', 'not_configured']);

/** Kinds where retrying the SAME file is the right advice. */
const RETRY_SAME_FILE = new Set([
  'parse_failed',
  'rate_limited',
  'ai_busy',
  'backend_unavailable',
  'network',
]);

function hintFor(kind: string): string | null {
  switch (kind) {
    case 'not_a_resume':
      return 'Check you picked the right file — this looked like a different kind of document.';
    case 'unparseable':
    case 'empty':
      return 'Scanned or photographed resumes have no text layer. Export a PDF from the original document instead.';
    case 'unsupported_format':
      return 'Only PDF and .docx are supported. Older .doc files need to be re-saved.';
    case 'file_too_large':
      return 'Most resumes are well under a megabyte — check you did not attach a portfolio.';
    case 'rate_limited':
      return 'Wait about a minute before trying again.';
    case 'ai_busy':
      return 'This usually clears in a few seconds.';
    case 'parse_failed':
      return 'Nothing was saved, so uploading again is safe.';
    default:
      return null;
  }
}

export function ResumeUpload({ accessToken, onUploaded }: ResumeUploadProps) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const confirm = useConfirmStatus();
  const [failure, setFailure] = useState<NormalizedUpload | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!file || busy) return;

    setBusy(true);
    setFailure(null);
    confirm.start();
    const result = await uploadResume(accessToken, file);
    if (result.ok) {
      await confirm.succeed();
      // `busy` is deliberately left true: onUploaded advances the page to the
      // review, and clearing it first would flash the idle form for a frame on
      // the way out. The processing timers are cleaned up by unmount.
      onUploaded(result, file.name);
      return;
    }
    // Every failure -- parse, network, timeout -- lands here, which is what
    // guarantees the processing state cannot outlive the request.
    confirm.fail();
    setFailure(result);
    setBusy(false);
  }

  function clearSelection() {
    setFile(null);
    setFailure(null);
    if (inputRef.current) inputRef.current.value = '';
  }

  const hint = failure ? hintFor(failure.kind) : null;

  return (
    <div className="login-bg">
      <div className="login-card resume-card">
        <div className="login-header">
          <h1 className="login-logo">GradusIQ</h1>
          <p className="login-subtitle">Add your resume</p>
        </div>

        <form className="login-form" onSubmit={handleSubmit}>
          {/* Instructions for an action already taken. Hidden while working so
              the panel's own trust line is the only promise on screen -- the
              intro, the footnote and the panel otherwise say the same thing
              three times, and three statements of "nothing is saved yet" read
              as protesting rather than reassuring. */}
          {!busy && (
            <p className="resume-intro">
              Upload your resume and we will pull out your experience, projects, and
              certifications. You will get to review and correct everything before anything is
              saved to your profile.
            </p>
          )}

          {/* The picker gives way to the processing panel rather than sitting
              disabled beside it: the panel already names the file, so nothing
              about what is being read is lost, and a greyed-out input next to
              an active status reads as two competing controls. */}
          {busy ? (
            <ProcessingStatus
              kind="resume"
              fileName={file?.name ?? 'Your resume'}
              active
              // The only place this promise appears while working -- the intro
              // and footnote that otherwise carry it are hidden below.
              note={RESUME_TRUST_NOTE}
            />
          ) : (
            <div className="form-group">
              <label className="form-label" htmlFor="resume-file">
                Resume file
              </label>
              <input
                id="resume-file"
                ref={inputRef}
                className="form-input resume-file-input"
                type="file"
                accept={ACCEPTED}
                onChange={(event) => {
                  setFile(event.target.files?.[0] ?? null);
                  setFailure(null);
                }}
              />
              <p className="resume-file-note">PDF or Word (.docx), up to 10 MB.</p>
            </div>
          )}

          {failure && (
            <div className="login-error" role="alert">
              <p>{failure.message}</p>
              {hint && <p className="resume-error-hint">{hint}</p>}
              {failure.kind === 'parse_failed' && failure.errors.length > 0 && (
                <p className="resume-error-detail">{failure.errors[0]}</p>
              )}
            </div>
          )}

          <ConfirmButton
            type="submit"
            className="btn btn-primary btn-full"
            status={confirm.status}
            disabled={!file || busy}
          >
            {confirm.status === 'success' ? 'Uploaded' : busy ? processingLabel('resume') : 'Upload resume'}
          </ConfirmButton>

          {failure && !NOT_RETRYABLE.has(failure.kind) && (
            <button
              type="button"
              className="btn btn-ghost btn-full"
              onClick={clearSelection}
              disabled={busy}
            >
              {RETRY_SAME_FILE.has(failure.kind) ? 'Start over' : 'Choose a different file'}
            </button>
          )}
        </form>

        {!busy && (
          <p className="login-note">
            Reading a resume takes a few seconds. Nothing is saved to your profile until you
            confirm it on the next screen.
          </p>
        )}
      </div>
    </div>
  );
}
