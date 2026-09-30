import React from 'react';
import ReactDOM from 'react-dom/client';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import type { Session } from '@supabase/supabase-js';
import { AuthContext, type AuthContextValue } from './auth/AuthContext';
import { ResetPasswordRequestPage } from './pages/ResetPasswordRequestPage';
import { ResetPasswordConfirmPage } from './pages/ResetPasswordConfirmPage';
import { LoginPage } from './pages/LoginPage';
import './index.css';
import './interaction.ts';

/**
 * Harness for both reset-password pages, mirroring signupPreview.tsx's shape.
 *
 * `?entry=` selects which page mounts first (MemoryRouter's initial route):
 *   request  -- /reset-password
 *   confirm  -- /reset-password/confirm
 *
 * `?mode=` selects what the stubbed AuthContext methods do:
 *   success        -- requestPasswordReset / confirmPasswordReset resolve;
 *                     confirm entry: a real recovery session (session +
 *                     isPasswordRecovery both true)
 *   error          -- they reject; confirm entry: same recovery session as
 *                     success, so the form renders and the rejection is
 *                     what's under test
 *   no-session     -- confirm entry only: session stays null (expired-link,
 *                     never-had-a-token case)
 *   signed-in      -- confirm entry only: session present but
 *                     isPasswordRecovery false -- an ordinary already-signed-
 *                     in student navigating to this URL directly, never
 *                     having opened a reset link at all
 *   loading        -- confirm entry only: sessionLoading stays true forever
 *
 * Calls are recorded on `document.body.dataset`, the same convention
 * signupPreview.tsx uses, so a test can assert on what was actually invoked
 * without reaching into React internals.
 */
const params = new URLSearchParams(location.search);
const entry = params.get('entry') ?? 'request';
const mode = params.get('mode') ?? 'success';

const requestPasswordReset = async (email: string): Promise<void> => {
  const calls = Number(document.body.dataset.resetRequestCalls ?? '0') + 1;
  document.body.dataset.resetRequestCalls = String(calls);
  document.body.dataset.resetRequestEmail = email;
  if (mode === 'error') throw new Error('Rate limited.');
};

const confirmPasswordReset = async (newPassword: string): Promise<void> => {
  const calls = Number(document.body.dataset.resetConfirmCalls ?? '0') + 1;
  document.body.dataset.resetConfirmCalls = String(calls);
  document.body.dataset.resetConfirmPassword = newPassword;
  if (mode === 'error') throw new Error('Auth session missing.');
};

const fakeSession = { user: { id: 'stub-user' } } as unknown as Session;

const context = {
  profile: null,
  slug: null,
  loading: false,
  profileLoading: false,
  sessionLoading: mode === 'loading',
  login: async () => {},
  logout: () => {},
  updateCareer: async () => {},
  resetCareer: async () => {},
  session: mode === 'no-session' || mode === 'loading' ? null : fakeSession,
  user: null,
  // Only a real recovery session ('success'/'error') is also a
  // PASSWORD_RECOVERY session. 'signed-in' is the regression case: a session
  // exists but it never came from a reset link.
  isPasswordRecovery: mode === 'success' || mode === 'error',
  signInWithPassword: async () => {},
  requestPasswordReset,
  confirmPasswordReset,
  signUpWithPassword: async () => 'authenticated' as const,
  signOutSession: async () => {},
  studentAccount: { status: 'no-session', profile: null, message: null },
  refreshStudentAccount: () => {},
  reloadStudentProfile: async () => {},
} as AuthContextValue;

/** Stands in for the real /login so post-confirm navigation is observable. */
function LoginStub() {
  return <LoginPage />;
}

const initialEntry = entry === 'confirm' ? '/reset-password/confirm' : '/reset-password';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AuthContext.Provider value={context}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/reset-password" element={<ResetPasswordRequestPage />} />
          <Route path="/reset-password/confirm" element={<ResetPasswordConfirmPage />} />
          <Route path="/login" element={<LoginStub />} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>
  </React.StrictMode>,
);
