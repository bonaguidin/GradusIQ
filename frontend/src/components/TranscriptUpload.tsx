import { useRef, useState } from 'react';
import { uploadTranscript } from '../api/transcript';
import { ProcessingStatus, processingLabel } from './ProcessingStatus';
import type { TranscriptUploadResult } from '../lib/transcriptApi.mjs';
import { GENERIC_TRANSCRIPT_STEPS, isAcceptedTranscriptFile, transcriptSourceFor } from '../lib/transcriptSources.mjs';

export interface TranscriptUploadProps {
  accessToken: string;
  onUploaded(result: TranscriptUploadResult, fileName: string): void;
  /** Home institution name, used to show where to download the transcript. */
  institutionName?: string | null;
}

/**
 * What to tell the student for each way an upload can fail.
 *
 * The backend went to deliberate trouble to keep these distinguishable -- two
 * different 413s, and an "encrypted" extraction status that exists as its own
 * status precisely so callers can branch on it. Collapsing them back into one
 * "we could not process that file" throws that away, and it throws away the
 * only part the student can act on: these three failures have three different
 * fixes, and one of them takes ten seconds.
 *
 * The backend's own message is shown underneath as the detail line; this is
 * the actionable headline it cannot supply.
 */
const FAILURE_GUIDANCE: Record<string, { title: string; action: string }> = {
  encrypted: {
    title: 'That PDF is password-protected',
    action:
      'Open it, enter the password, and save or print a copy without protection — then upload that copy. Most registrar PDFs allow this.',
  },
  file_too_large: {
    title: 'That file is over 10 MB',
    action:
      'Export or scan your transcript at a smaller size, or save it as a PDF from your student portal rather than photographing it.',
  },
  transcript_too_long: {
    title: 'That transcript has too much content to read at once',
    action:
      'This is about length, not file size — a smaller file will not help. Upload a transcript covering fewer terms, or contact support.',
  },
  unsupported_format: {
    title: 'That file type is not supported',
    action: 'Upload a PDF or a Word (.docx) file. Images and scans without selectable text cannot be read.',
  },
  not_a_transcript: {
    title: 'That does not look like a transcript',
    action: 'Check you uploaded your academic transcript rather than a resume or another document.',
  },
};

export function TranscriptUpload({ accessToken, onUploaded, institutionName }: TranscriptUploadProps) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<TranscriptUploadResult | null>(null);
  const [dragging, setDragging] = useState(false);
  const [dropError, setDropError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const source = transcriptSourceFor(institutionName);

  /**
   * A dropped file goes through the same <input> the picker uses, so submit
   * and every test that drives #transcript-file see one code path. A drop
   * skips the input's `accept` filter, so the extension is checked here.
   */
  function handleDrop(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    if (busy) return;
    const dropped = event.dataTransfer.files[0];
    if (!dropped) return;
    if (!isAcceptedTranscriptFile(dropped.name)) {
      setDropError('That file type is not supported. Drop a PDF or Word (.docx) file.');
      return;
    }
    if (input.current) {
      const transfer = new DataTransfer();
      transfer.items.add(dropped);
      input.current.files = transfer.files;
    }
    setDropError(null);
    setFailure(null);
    setFile(dropped);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!file || busy) return;
    setBusy(true);
    setFailure(null);
    const result = await uploadTranscript(accessToken, file);
    if (result.ok) {
      // `busy` stays true on success -- see ResumeUpload's submit for the
      // reasoning. The processing timers are cleaned up by unmount.
      onUploaded(result, file.name);
      return;
    }
    // Every failure -- parse, network, timeout -- lands here, which is what
    // guarantees the processing state cannot outlive the request.
    setFailure(result);
    setBusy(false);
  }

  const guidance = failure ? FAILURE_GUIDANCE[failure.kind] : null;

  return (
    <div className="rv-bg">
      <div className="rv-page rv-page-narrow">
        <header className="rv-masthead">
          <div className="rv-masthead-top">
            <span className="rv-wordmark">GradusIQ</span>
          </div>
          <h1 className="rv-headline">Add your transcript.</h1>
          <p className="rv-standfirst">
            Upload an academic transcript and we&rsquo;ll read the courses off it. Nothing is saved
            to your record until you&rsquo;ve checked every line.
          </p>
        </header>

        {/* Finding the file is the slow part, not uploading it. Named steps
            and a direct link for the student's own school; generic steps
            otherwise. An unofficial transcript is enough. */}
        <section className="rv-upload-source" aria-label="Where to get your transcript">
          <h2 className="rv-upload-label">
            {source ? `Get your unofficial transcript from ${source.portalName}` : 'Get your unofficial transcript'}
          </h2>
          <ol className="rv-upload-source-steps">
            {(source?.steps ?? GENERIC_TRANSCRIPT_STEPS).map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
          {source && (
            <a className="rv-upload-source-link" href={source.portalUrl} target="_blank" rel="noreferrer">
              Open {source.portalName} ↗
            </a>
          )}
        </section>

        <form onSubmit={submit} className="rv-upload">
          {/* The picker gives way to the processing panel rather than sitting
              disabled beside it -- see ResumeUpload for the same decision. */}
          {busy ? (
            // No `note`: the masthead standfirst above already says nothing is
            // saved until every line is checked, and it stays put through
            // processing. Repeating it inside the panel would be the same
            // reassurance twice on one screen.
            <ProcessingStatus
              kind="transcript"
              fileName={file?.name ?? 'Your transcript'}
              active
            />
          ) : (
            <div
              className={dragging ? 'rv-upload-drop is-dragging' : 'rv-upload-drop'}
              onDragOver={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={handleDrop}
            >
              <label className="rv-upload-label" htmlFor="transcript-file">
                Transcript file
              </label>
              <input
                id="transcript-file"
                ref={input}
                type="file"
                accept=".pdf,.docx"
                onChange={(event) => {
                  setFile(event.target.files?.[0] ?? null);
                  setFailure(null);
                  setDropError(null);
                }}
              />
              <p className="rv-upload-help">
                Choose the file or drop it here. PDF or Word (.docx), up to 10 MB. Scanned
                documents without selectable text cannot be read.
              </p>
              {dropError && <p className="rv-upload-drop-error" role="alert">{dropError}</p>}
            </div>
          )}

          {failure && (
            <div className="rv-upload-error" role="alert">
              <strong className="rv-upload-error-title">
                {guidance?.title ?? 'We could not process that file'}
              </strong>
              {guidance && <p className="rv-upload-error-action">{guidance.action}</p>}
              <p className="rv-upload-error-detail">{failure.message}</p>
            </div>
          )}

          <button className="rv-commit-button" type="submit" disabled={!file || busy}>
            {busy ? processingLabel('transcript') : 'Upload transcript'}
          </button>

          {failure && (
            <button
              className="rv-upload-reset"
              type="button"
              disabled={busy}
              onClick={() => {
                setFile(null);
                setFailure(null);
                if (input.current) input.current.value = '';
              }}
            >
              Choose another file
            </button>
          )}
        </form>

        {/* Hidden while working: the processing panel already carries the
            "nothing is added until you confirm" promise, and stating it twice
            on the same screen weakens both. */}
        {!busy && (
          <p className="rv-upload-footnote">
            Reading a transcript takes a few seconds. Parsed courses stay pending until you
            confirm them.
          </p>
        )}
      </div>
    </div>
  );
}
