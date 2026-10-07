import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { INSTITUTIONS, todayIso, validateSignupForm } from '../lib/signupRules.mjs';

/**
 * Account creation, which ends in one of two places depending on a project
 * setting this code does not control.
 *
 * THE BUG THIS SHAPE EXISTS TO PREVENT. This page used to treat "signUp() did
 * not throw" as "a confirmation email is on its way", and showed the check-your-
 * email screen unconditionally. That is only true when the project has "Confirm
 * email" ON. With it OFF -- which is how the live project is configured
 * (mailer_autoconfirm: true, read from /auth/v1/settings) -- GoTrue confirms
 * the address inline and returns a session, so the student was fully signed in
 * and fully provisioned while being told to go open a link that was never sent.
 * The account created by the reported failure proves it: email_confirmed_at was
 * set 51ms after created_at, last_sign_in_at was set 8ms after that, and both
 * its students and student_institutions rows existed.
 *
 * So the branch is on the session, the one field that differs between the two
 * configurations, and BOTH endings stay supported: the setting can be switched
 * back on, and other deployments may run with it enabled.
 *
 * ON NOT PROVISIONING HERE. The authenticated branch only navigates. The
 * students row is created by AuthContext's provisioning effect, which fires on
 * the session that signUp() just produced -- the same path a normal sign-in
 * takes. RequireAuth holds /dashboard on a spinner via `studentAccount.status`
 * until that finishes, so navigating immediately is safe and needs no timer.
 */
export function SignUpPage() {
  const { signUpWithPassword } = useAuth();
  const navigate = useNavigate();

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [institutionId, setInstitutionId] = useState<string>(INSTITUTIONS[0].id);
  const [dateOfBirth, setDateOfBirth] = useState('');

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    // Every client-side rule, including the age gate, runs before any network
    // call. An underage or malformed submission never reaches signUp().
    const problem = validateSignupForm(
      { name, email, password, institutionId, dateOfBirth },
      todayIso(),
    );
    if (problem) {
      setError(problem);
      return;
    }

    setSubmitting(true);
    try {
      const outcome = await signUpWithPassword(email.trim(), password, {
        name: name.trim(),
        institution_id: institutionId,
        date_of_birth: dateOfBirth,
      });

      if (outcome === 'authenticated') {
        // Signed in already. Mirrors LoginPage's post-sign-in navigation
        // exactly, rather than inventing a second way into the dashboard.
        void navigate('/dashboard');
        return;
      }

      setSentTo(email.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-up failed.');
    } finally {
      // Runs on the authenticated branch too. Navigation unmounts this page, so
      // the update is a no-op there; leaving it unconditional keeps the button
      // from staying stuck on "Creating account…" if navigation is ever gated.
      setSubmitting(false);
    }
  }

  if (sentTo) {
    return (
      <div className="login-bg">
        <div className="login-card">
          <div className="login-header">
            <h1 className="login-logo">GradusIQ</h1>
            <p className="login-subtitle">Check your email</p>
          </div>

          <div className="login-form">
            <p>
              We sent a confirmation link to <strong>{sentTo}</strong>. Open it to activate your
              account, then sign in — your profile is set up on that first sign-in.
            </p>
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
          <p className="login-subtitle">Create your student account</p>
        </div>

        <form
          onSubmit={(e) => {
            void handleSubmit(e);
          }}
          className="login-form"
        >
          <div className="form-group">
            <label htmlFor="signup-name" className="form-label">
              Full name
            </label>
            <input
              id="signup-name"
              name="name"
              type="text"
              className="form-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={submitting}
              autoComplete="name"
              required
            />
          </div>

          <div className="form-group">
            <label htmlFor="signup-email" className="form-label">
              Email
            </label>
            <input
              id="signup-email"
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

          <div className="form-group">
            <label htmlFor="signup-password" className="form-label">
              Password
            </label>
            <input
              id="signup-password"
              name="new-password"
              type="password"
              className="form-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={submitting}
              autoComplete="new-password"
              required
            />
          </div>

          <div className="form-group">
            <label htmlFor="signup-dob" className="form-label">
              Date of birth
            </label>
            <input
              id="signup-dob"
              name="bday"
              type="date"
              className="form-input"
              value={dateOfBirth}
              onChange={(e) => setDateOfBirth(e.target.value)}
              disabled={submitting}
              max={todayIso()}
              autoComplete="bday"
              required
            />
          </div>

          <div className="form-group">
            <label htmlFor="signup-institution" className="form-label">
              Institution
            </label>
            <select
              id="signup-institution"
              name="institution"
              className="form-select"
              value={institutionId}
              onChange={(e) => setInstitutionId(e.target.value)}
              disabled={submitting}
            >
              {INSTITUTIONS.map((institution) => (
                <option key={institution.id} value={institution.id}>
                  {institution.name}
                </option>
              ))}
            </select>
          </div>

          {error && (
            <p className="login-error" role="alert">
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
                Creating account…
              </span>
            ) : (
              'Create account'
            )}
          </button>
        </form>

        <p className="login-note">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      </div>
    </div>
  );
}
