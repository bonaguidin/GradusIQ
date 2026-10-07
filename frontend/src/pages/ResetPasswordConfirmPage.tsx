import { useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { useErrorFocus } from '../hooks/useErrorFocus';
import { Spinner } from '../auth/AccountStateScreens';

/**
 * Landed on via the emailed link. supabase-js's `detectSessionInUrl` (on by
 * default, confirmed in the installed @supabase/auth-js) parses the URL
 * fragment on load and establishes a recovery session, firing
 * onAuthStateChange with a PASSWORD_RECOVERY event. AuthContext's existing
 * top-level listener already picks that event up into `isPasswordRecovery`
 * -- this page reads that flag from useAuth() rather than opening a second
 * subscription.
 *
 * The gate below checks `isPasswordRecovery`, not merely `session`: a
 * session alone is not evidence a reset link was ever opened -- an ordinary
 * already-signed-in student navigating straight to this URL would also have
 * one, and letting `session` alone through the gate previously meant that
 * student could reach the "choose a new password" form with no reset flow
 * behind it at all.
 */
export function ResetPasswordConfirmPage() {
  const { sessionLoading, session, isPasswordRecovery, confirmPasswordReset } = useAuth();
  const navigate = useNavigate();

  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const errorRef = useRef<HTMLParagraphElement>(null);
  useErrorFocus(error, errorRef);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (newPassword !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }
    if (newPassword.length < 6) {
      setError('Choose a password of at least 6 characters.');
      return;
    }

    setSubmitting(true);
    try {
      await confirmPasswordReset(newPassword);
      void navigate('/login', { state: { passwordResetSuccess: true } });
    } catch {
      // Never a raw Supabase error string -- translated to a friendly message.
      setError('Could not update your password. Your reset link may have expired.');
    } finally {
      setSubmitting(false);
    }
  }

  if (sessionLoading) {
    return <Spinner />;
  }

  if (!session || !isPasswordRecovery) {
    return (
      <div className="login-bg">
        <div className="login-card">
          <div className="login-header">
            <h1 className="login-logo">GradusIQ</h1>
            <p className="login-subtitle">Reset link expired</p>
          </div>

          <div className="login-form">
            <p className="login-error" role="alert">
              This password reset link is invalid or has expired.
            </p>
          </div>

          <p className="login-note">
            <Link to="/reset-password">Request a new reset link</Link>
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="login-bg">
      <div className="login-card">
        <div className="login-header">
          <h1 className="login-logo">GradusIQ</h1>
          <p className="login-subtitle">Choose a new password</p>
        </div>

        <form
          onSubmit={(e) => {
            void handleSubmit(e);
          }}
          className="login-form"
        >
          <div className="form-group">
            <label htmlFor="new-password" className="form-label">
              New password
            </label>
            <input
              id="new-password"
              type="password"
              className="form-input"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              disabled={submitting}
              autoComplete="new-password"
              required
            />
          </div>

          <div className="form-group">
            <label htmlFor="confirm-password" className="form-label">
              Confirm new password
            </label>
            <input
              id="confirm-password"
              type="password"
              className="form-input"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              disabled={submitting}
              autoComplete="new-password"
              required
            />
          </div>

          {error && (
            <p className="login-error" role="alert" tabIndex={-1} ref={errorRef}>
              {error}
            </p>
          )}

          <button
            type="submit"
            className="btn btn-primary btn-full"
            disabled={submitting}
            aria-busy={submitting}
          >
            {submitting ? (
              <span className="btn-loading">
                <span className="spinner-small" aria-hidden="true" />
                Updating…
              </span>
            ) : (
              'Update password'
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
