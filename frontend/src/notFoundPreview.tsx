import React from 'react';
import ReactDOM from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import type { Session } from '@supabase/supabase-js';
import { AuthContext, type AuthContextValue } from './auth/AuthContext';
import { NotFoundPage } from './pages/NotFoundPage';
import './index.css';
import './interaction.ts';

// ?signedIn=0 shows the signed-out version (one "Go to sign in" button);
// anything else has a session, so both ways back into the app show.
const signedIn = new URLSearchParams(location.search).get('signedIn') !== '0';

const context = {
  profile: null, slug: null, loading: false, profileLoading: false, sessionLoading: false,
  login: async () => {}, logout: () => {}, updateCareer: async () => {}, resetCareer: async () => {},
  session: signedIn ? ({ access_token: 'preview-access-token' } as Session) : null,
  user: null, isPasswordRecovery: false, signInWithPassword: async () => {}, requestPasswordReset: async () => {}, confirmPasswordReset: async () => {}, signUpWithPassword: async () => 'authenticated', signOutSession: async () => {},
  studentAccount: { status: 'checking', profile: null, message: null },
  refreshStudentAccount: () => {},
  reloadStudentProfile: async () => {},
} as unknown as AuthContextValue;

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AuthContext.Provider value={context}>
      <MemoryRouter initialEntries={['/some/old-link']}>
        <NotFoundPage />
      </MemoryRouter>
    </AuthContext.Provider>
  </React.StrictMode>,
);
