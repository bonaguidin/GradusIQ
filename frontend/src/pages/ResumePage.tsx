import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { ResumeUpload } from '../components/ResumeUpload';
import { CareerReview } from '../components/CareerReview';
import { fetchCareerReview } from '../api/resume';
import { resumeSuccessState } from '../lib/successNotice.mjs';
import type {
  NormalizedReview,
  NormalizedUpload,
  ResumeAcademicFacts,
  ReviewSections,
} from '../lib/resumeApi.mjs';

/**
 * NO 'done' STEP, BY DESIGN -- see TranscriptPage for the same decision stated
 * in full. This page previously argued the opposite: that a static success
 * screen let the student "review the completed step at their own pace". What
 * that screen actually offered to review was a count of rows, and the pace it
 * protected was the pace of pressing one more button to reach the only place
 * the flow could go. Confirmation now navigates to /dashboard, where the saved
 * data itself is the confirmation and DashboardSuccessNotice supplies the
 * sentence.
 */
type Step = 'checking' | 'upload' | 'review' | 'recovery_error';

/**
 * The three-step resume flow, held on one route.
 */
export function ResumePage() {
  const { session } = useAuth();
  const accessToken = session?.access_token ?? '';

  return accessToken ? <ResumeFlow accessToken={accessToken} /> : <ResumeLoading />;
}

export function ResumeFlow({ accessToken }: { accessToken: string }) {
  const navigate = useNavigate();
  const { reloadStudentProfile } = useAuth();
  const [step, setStep] = useState<Step>('checking');
  const [recoveredSections, setRecoveredSections] = useState<ReviewSections | null>(null);
  const [recoveryFailure, setRecoveryFailure] = useState<NormalizedReview | null>(null);
  const [recoveryAttempt, setRecoveryAttempt] = useState(0);
  // Provenance for the review masthead. Held here because it is the only place
  // that sees both the upload and the review step.
  const [source, setSource] = useState<{ name: string; at: Date } | null>(null);
  const [academicFacts, setAcademicFacts] = useState<ResumeAcademicFacts | null>(null);

  useEffect(() => {
    let active = true;
    setStep('checking');
    setRecoveryFailure(null);
    void fetchCareerReview(accessToken).then((result) => {
      if (!active) return;
      if (!result.ok) {
        setRecoveryFailure(result);
        setStep('recovery_error');
        return;
      }
      if (result.pendingCount > 0) {
        setRecoveredSections(result.sections);
        setStep('review');
      } else {
        setRecoveredSections(null);
        setStep('upload');
      }
    });
    return () => {
      active = false;
    };
  }, [accessToken, recoveryAttempt]);

  function handleUploaded(result: NormalizedUpload, fileName: string) {
    setRecoveredSections(null);
    setAcademicFacts(result.academics);
    setSource({ name: fileName, at: new Date() });
    setStep('review');
  }

  /**
   * Runs only on a confirmed backend success -- CareerReview keeps failures and
   * timeouts on the review screen and never calls this.
   *
   * The canonical profile is re-read before navigating for the same reason as
   * the transcript flow: the dashboard's career section renders from
   * `studentAccount.profile`, which predates this confirmation and would
   * otherwise greet the student with "no confirmed career profile yet".
   */
  async function handleConfirmed() {
    await reloadStudentProfile();
    await navigate('/dashboard', { replace: true, state: resumeSuccessState() });
  }

  // stage-section (index.css) is the same fade+rise every dashboard section
  // switch already uses -- reused here so checking/upload/review/error no
  // longer swap in as a hard cut. Each branch is a genuinely new mount (an
  // early return of a different tree), so the animation always replays with
  // no extra key/attribute needed.
  if (step === 'checking') return <div className="stage-section"><ResumeLoading /></div>;

  if (step === 'recovery_error') {
    return (
      <div className="login-bg stage-section">
        <div className="login-card">
          <div className="login-header">
            <h1 className="login-logo">GradusIQ</h1>
            <p className="login-subtitle">Could not check your resume</p>
          </div>
          <div className="login-form">
            <p className="login-error" role="alert">
              {recoveryFailure?.message ?? 'Your saved review could not be checked.'}
            </p>
            <button
              type="button"
              className="btn btn-primary btn-full"
              onClick={() => setRecoveryAttempt((attempt) => attempt + 1)}
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
        <ResumeUpload accessToken={accessToken} onUploaded={handleUploaded} />
      </div>
    );
  }

  if (step === 'review') {
    return (
      <div className="stage-section">
        <CareerReview
          accessToken={accessToken}
          onConfirmed={() => {
            void handleConfirmed();
          }}
          initialSections={recoveredSections ?? undefined}
          sourceName={source?.name}
          parsedAt={source?.at}
          academicFacts={academicFacts ?? undefined}
        />
      </div>
    );
  }

  // No terminal state left to fall through to.
  return <div className="stage-section"><ResumeLoading /></div>;
}

function ResumeLoading() {
  return (
    <div className="loading-screen">
      <div className="spinner" role="status" aria-label="Checking for a saved resume review" />
    </div>
  );
}
