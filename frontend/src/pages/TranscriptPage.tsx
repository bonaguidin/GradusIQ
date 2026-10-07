import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { fetchTranscriptReview } from '../api/transcript';
import { TranscriptUpload } from '../components/TranscriptUpload';
import { TranscriptReview } from '../components/TranscriptReview';
import { transcriptSuccessState } from '../lib/successNotice.mjs';
import type {
  TranscriptConfirmResult,
  TranscriptReviewResult,
  TranscriptUploadResult,
} from '../lib/transcriptApi.mjs';

/**
 * NO 'done' STEP, BY DESIGN. Confirming used to land on a terminal "your
 * transcript is saved" card whose only content was a count and a "Go to
 * dashboard" link -- a screen whose entire purpose was to ask for a click that
 * had no alternative. The confirmation now goes to /dashboard itself and says
 * what happened once it is there (DashboardSuccessNotice).
 *
 * The step machine is the structural guarantee: with no completed state to
 * render, a future change cannot quietly reintroduce a done screen without
 * first reintroducing a state for it.
 */
type Step = 'checking' | 'upload' | 'review' | 'error';

export function TranscriptPage() {
  const { session } = useAuth();
  return session?.access_token ? (
    <TranscriptFlow accessToken={session.access_token} />
  ) : (
    <TranscriptLoading />
  );
}

export function TranscriptFlow({ accessToken }: { accessToken: string }) {
  const navigate = useNavigate();
  const { reloadStudentProfile } = useAuth();
  const [step, setStep] = useState<Step>('checking');
  const [review, setReview] = useState<TranscriptReviewResult | null>(null);
  const [sourceName, setSourceName] = useState<string>();
  const [uploadResult, setUploadResult] = useState<TranscriptUploadResult | null>(null);
  const [attempt, setAttempt] = useState(0);

  /**
   * Runs only on a confirmed backend success -- TranscriptReview keeps every
   * failure, timeout and grade-scale block on the review screen and never calls
   * this. Nothing here is optimistic.
   *
   * The profile is re-read BEFORE navigating, not after. The dashboard renders
   * from `studentAccount.profile`, which was fetched when the session was
   * resolved and knows nothing about the courses just written; arriving first
   * and refreshing second would show the student a dashboard that still says
   * "no confirmed transcript data yet" and then rewrite it under them. Awaiting
   * costs one request and the review screen stays under its own saving overlay
   * for the duration.
   */
  async function handleConfirmed(result: TranscriptConfirmResult) {
    await reloadStudentProfile();
    // replace: the review no longer exists on the server, so Back must not
    // return to it.
    await navigate('/dashboard', { replace: true, state: transcriptSuccessState(result.confirmed) });
  }

  async function load() {
    setStep('checking');
    const result = await fetchTranscriptReview(accessToken);
    setReview(result);
    setStep(result.ok ? (result.records.length ? 'review' : 'upload') : 'error');
  }

  useEffect(() => {
    let active = true;
    setStep('checking');
    void fetchTranscriptReview(accessToken).then((result) => {
      if (!active) return;
      setReview(result);
      setStep(result.ok ? (result.records.length ? 'review' : 'upload') : 'error');
    });
    return () => {
      active = false;
    };
  }, [accessToken, attempt]);

  // stage-section (index.css) is the same fade+rise every dashboard section
  // switch already uses -- reused here so checking/upload/review/error no
  // longer swap in as a hard cut. Each branch is a genuinely new mount (an
  // early return of a different tree), so the animation always replays with
  // no extra key/attribute needed.
  if (step === 'checking') return <div className="stage-section"><TranscriptLoading /></div>;

  if (step === 'error') {
    return (
      <div className="login-bg stage-section">
        <div className="login-card">
          <div className="login-header">
            <h1 className="login-logo">GradusIQ</h1>
            <p className="login-subtitle">Could not check your transcript</p>
          </div>
          <div className="login-form">
            <p className="login-error" role="alert">
              {review?.message ?? 'Your saved transcript review could not be loaded.'}
            </p>
            <button
              type="button"
              className="btn btn-primary btn-full"
              onClick={() => setAttempt((value) => value + 1)}
            >
              Try again
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (step === 'upload') {
    return (
      <div className="stage-section">
        <TranscriptUpload
          accessToken={accessToken}
          onUploaded={async (upload: TranscriptUploadResult, fileName: string) => {
            setUploadResult(upload);
            setSourceName(fileName);
            await load();
          }}
        />
      </div>
    );
  }

  if (step === 'review' && review?.ok) {
    return (
      <div className="stage-section">
        <TranscriptReview
          accessToken={accessToken}
          review={review}
          uploadResult={uploadResult}
          sourceName={sourceName}
          onConfirmed={(result) => {
            void handleConfirmed(result);
          }}
        />
      </div>
    );
  }

  // 'review' with a failed review payload is unreachable (the loader only sets
  // it on result.ok), and there is no terminal state left to fall through to.
  return <div className="stage-section"><TranscriptLoading /></div>;
}

function TranscriptLoading() {
  return (
    <div className="loading-screen">
      <div className="spinner" role="status" aria-label="Checking for a saved transcript review" />
    </div>
  );
}
