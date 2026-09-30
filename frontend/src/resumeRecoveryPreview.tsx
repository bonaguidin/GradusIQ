// Test-only entry point for the persisted resume-flow state machine.
import { createRoot } from 'react-dom/client';
import { ResumeFlow } from './pages/ResumePage';
import { PreviewFlowHarness, PREVIEW_TOKEN } from './previewHarness';
import './index.css';
import './interaction.ts';

createRoot(document.getElementById('root')!).render(
  <PreviewFlowHarness>
    <ResumeFlow accessToken={PREVIEW_TOKEN} />
  </PreviewFlowHarness>,
);
