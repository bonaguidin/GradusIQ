import React from 'react';
import ReactDOM from 'react-dom/client';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { AuthContext, type AuthContextValue } from './auth/AuthContext';
import { SignUpPage } from './pages/SignUpPage';
import type { SignupOutcome } from './lib/signupRules.mjs';
import './index.css';
import './interaction.ts';

/**
 * Harness for the sign-up page's two endings.
 *
 * `?mode=` selects what signUp() is pretending the project's "Confirm email"
 * setting is, which is the only thing that decides which ending is correct:
 *
 *   session       -- confirmation OFF: a session comes back, so the student is
 *                    already signed in and belongs on the dashboard.
 *   confirmation  -- confirmation ON: a user but no session, so the
 *                    check-your-email screen is right.
 *   error         -- signUp() rejected.
 *
 * The stub records every call on `document.body.dataset`, which is what lets a
 * test assert the page did NOT provision anything itself: this harness provides
 * no provisioning path at all, so a page that tried to do its own would fail
 * here rather than silently double-write in production.
 */
const mode = new URLSearchParams(location.search).get('mode') ?? 'session';

const signUpWithPassword = async (
  email: string,
  _password: string,
  metadata: { name: string; institution_id: string; date_of_birth: string },
): Promise<SignupOutcome> => {
  const calls = Number(document.body.dataset.signupCalls ?? '0') + 1;
  document.body.dataset.signupCalls = String(calls);
  document.body.dataset.signupEmail = email;
  // The institution the student picked has to survive as far as the call that
  // provisioning later reads it back from -- it is what student_institutions
  // needs, and it is the field a form-to-metadata mistake would drop.
  document.body.dataset.signupMetadata = JSON.stringify(metadata);

  if (mode === 'error') throw new Error('Password is too weak.');
  return mode === 'confirmation' ? 'confirmation-required' : 'authenticated';
};

const context = {
  profile: null,
  slug: null,
  loading: false,
  profileLoading: false,
  sessionLoading: false,
  login: async () => {},
  logout: () => {},
  updateCareer: async () => {},
  resetCareer: async () => {},
  session: null,
  user: null,
  isPasswordRecovery: false,
  signInWithPassword: async () => {},
  requestPasswordReset: async () => {},
  confirmPasswordReset: async () => {},
  signUpWithPassword,
  signOutSession: async () => {},
  studentAccount: { status: 'no-session', profile: null, message: null },
  refreshStudentAccount: () => {},
  reloadStudentProfile: async () => {},
} as AuthContextValue;

/** Stands in for the real /dashboard so navigation is observable without
 *  pulling RequireAuth and the whole dashboard into this harness. */
function DashboardStub() {
  return <h1>Dashboard reached</h1>;
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AuthContext.Provider value={context}>
      <MemoryRouter initialEntries={['/signup']}>
        <Routes>
          <Route path="/signup" element={<SignUpPage />} />
          <Route path="/dashboard" element={<DashboardStub />} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>
  </React.StrictMode>,
);
