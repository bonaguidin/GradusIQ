import { Routes, Route, Navigate } from 'react-router-dom';
import { LoginPage } from './pages/LoginPage';
import { SignUpPage } from './pages/SignUpPage';
import { ResetPasswordRequestPage } from './pages/ResetPasswordRequestPage';
import { ResetPasswordConfirmPage } from './pages/ResetPasswordConfirmPage';
import { DashboardPage } from './pages/DashboardPage';
import { ResumePage } from './pages/ResumePage';
import { TranscriptPage } from './pages/TranscriptPage';
import { ProfileCompletionPage } from './pages/ProfileCompletionPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { RequireAuth } from './auth/RequireAuth';
import { RequireStudentAccount } from './auth/RequireStudentAccount';

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignUpPage />} />
      <Route path="/reset-password" element={<ResetPasswordRequestPage />} />
      <Route path="/reset-password/confirm" element={<ResetPasswordConfirmPage />} />
      {/* RequireAuth admits either a demo profile or a ready student account;
          DashboardPage keeps their data paths separate. */}
      <Route
        path="/dashboard"
        element={
          <RequireAuth>
            <DashboardPage />
          </RequireAuth>
        }
      />
      {/*
        /resume uses the narrower gate. RequireAuth would admit a demo session
        via its `if (profile)` short-circuit, and demo students have no Postgres
        rows, so every call this flow makes would 404 for them.
      */}
      <Route
        path="/resume"
        element={
          <RequireStudentAccount>
            <ResumePage />
          </RequireStudentAccount>
        }
      />
      <Route
        path="/transcript"
        element={<RequireStudentAccount><TranscriptPage /></RequireStudentAccount>}
      />
      <Route
        path="/profile/complete"
        element={<RequireStudentAccount><ProfileCompletionPage /></RequireStudentAccount>}
      />
      {/* The bare domain still lands on sign-in (which forwards a signed-in
          student to /dashboard); only addresses nothing matches get the 404. */}
      <Route path="/" element={<Navigate to="/login" replace />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
