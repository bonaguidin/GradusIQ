import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';

/**
 * Requests a reset email. The success screen shows regardless of whether
 * requestPasswordReset() resolved or threw -- Supabase itself never reveals
 * account existence for this call, and neither should this page, so a
 * network/rate-limit error is swallowed the same way a nonexistent email is.
 */
export function ResetPasswordRequestPage() {
  const { requestPasswordReset } = useAuth();

  const [email, setEmail] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await requestPasswordReset(email.trim());
    } catch {
      // Deliberately ignored -- see the enumeration-prevention note above.
    } finally {
      setSubmitting(false);
      setSent(true);
    }
  }

  if (sent) {
    return (
      <div className="login-bg">
        <div className="login-card">
          <div className="login-header">
            <h1 className="login-logo">GradusIQ</h1>
            <p className="login-subtitle">Check your email</p>
          </div>

          <div className="login-form">
            <p>If an account exists for this email, a reset link has been sent.</p>
          </div>

          <p className="login-note">
            <Link to="/login">Back to sign in</Link>
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
          <p className="login-subtitle">Reset your password</p>
        </div>

        <form
          onSubmit={(e) => {
            void handleSubmit(e);
          }}
          className="login-form"
        >
          <div className="form-group">
            <label htmlFor="reset-email" className="form-label">
              Email
            </label>
            <input
              id="reset-email"
              name="email"
              type="email"
              className="form-input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={submitting}
              autoComplete="email"
              spellCheck={false}
              required
            />
          </div>

          <button
            type="submit"
            className="btn btn-primary btn-full"
            disabled={submitting}
            aria-busy={submitting}
          >
            {submitting ? (
              <span className="btn-loading">
                <span className="spinner-small" aria-hidden="true" />
                Sending…
              </span>
            ) : (
              'Send reset link'
            )}
          </button>
        </form>

        <p className="login-note">
          <Link to="/login">Back to sign in</Link>
        </p>
      </div>
    </div>
  );
}
