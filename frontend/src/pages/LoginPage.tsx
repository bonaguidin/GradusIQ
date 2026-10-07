import { useState, useEffect } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';

const DEMO_STUDENTS = [
  { name: 'Jordan Reyes',  slug: 'jordanReyes'  },
  { name: 'Ethan Brooks',  slug: 'ethanBrooks'  },
  { name: 'Marcus Webb',   slug: 'marcusWebb'   },
  { name: 'Priya Nair',    slug: 'priyaNair'    },
  { name: 'Sofia Ramirez', slug: 'sofiaRamirez' },
] as const;

export function LoginPage() {
  const { login, loading, profile, signInWithPassword } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const passwordResetSuccess = Boolean(
    (location.state as { passwordResetSuccess?: boolean } | null)?.passwordResetSuccess,
  );

  const [selectedSlug, setSelectedSlug] = useState<string>(DEMO_STUDENTS[0].slug);
  const [error, setError] = useState<string | null>(null);

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [credLoading, setCredLoading] = useState(false);
  const [credError, setCredError] = useState<string | null>(null);

  // Wait for React to flush the profile state before navigating
  useEffect(() => {
    if (profile && !loading) {
      void navigate('/dashboard');
    }
  }, [profile, loading, navigate]);

  async function handleCredentialSubmit(e: React.FormEvent) {
    e.preventDefault();
    setCredError(null);
    setCredLoading(true);
    try {
      await signInWithPassword(email, password);
      void navigate('/dashboard');
    } catch (err) {
      setCredError(err instanceof Error ? err.message : 'Sign-in failed.');
    } finally {
      setCredLoading(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await login(selectedSlug);
    } catch {
      setError('Failed to load student profile. Please try again.');
    }
  }

  return (
    <div className="login-bg">
      <div className="login-card">
        {/* Header — serif product name on white */}
        <div className="login-header">
          <h1 className="login-logo">GradusIQ</h1>
          <p className="login-subtitle">Sign in to your student account</p>
        </div>

        {passwordResetSuccess && (
          <p className="login-note" role="status">
            Password updated. Sign in with your new password.
          </p>
        )}

        <form
          onSubmit={(e) => { void handleCredentialSubmit(e); }}
          className="login-form"
        >
          <div className="form-group">
            <label htmlFor="login-email" className="form-label">
              Email
            </label>
            <input
              id="login-email"
              name="email"
              type="email"
              className="form-input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={credLoading}
              autoComplete="email"
              spellCheck={false}
              required
            />
          </div>

          <div className="form-group">
            <label htmlFor="login-password" className="form-label">
              Password
            </label>
            <input
              id="login-password"
              name="current-password"
              type="password"
              className="form-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={credLoading}
              autoComplete="current-password"
              required
            />
          </div>

          <p className="login-note">
            <Link to="/reset-password">Forgot password?</Link>
          </p>

          {credError && (
            <p className="login-error" role="alert">
              {credError}
            </p>
          )}

          <button
            type="submit"
            className="btn btn-primary btn-full"
            disabled={credLoading}
            aria-busy={credLoading}
          >
            {credLoading ? (
              <span className="btn-loading">
                <span className="spinner-small" aria-hidden="true" />
                Signing in…
              </span>
            ) : (
              'Sign in'
            )}
          </button>
        </form>

        <p className="login-note">
          Don&apos;t have an account? <Link to="/signup">Sign up</Link>
        </p>

        <p className="login-note">or explore a demo profile</p>

        <form
          onSubmit={(e) => { void handleSubmit(e); }}
          className="login-form"
        >
          <div className="form-group">
            <label htmlFor="student-select" className="form-label">
              Student profile
            </label>
            <select
              id="student-select"
              name="student-select"
              className="form-select"
              value={selectedSlug}
              onChange={(e) => setSelectedSlug(e.target.value)}
              disabled={loading}
            >
              {DEMO_STUDENTS.map((s) => (
                <option key={s.slug} value={s.slug}>
                  {s.name}
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
            className="btn btn-ghost btn-full"
            disabled={loading}
            aria-busy={loading}
          >
            {loading ? (
              <span className="btn-loading">
                <span className="spinner-small" aria-hidden="true" />
                Loading…
              </span>
            ) : (
              'Enter Dashboard'
            )}
          </button>
        </form>

        <p className="login-note">Demo mode — select a student profile to explore</p>
      </div>
    </div>
  );
}
