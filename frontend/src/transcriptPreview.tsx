import { createRoot } from 'react-dom/client';
import { TranscriptFlow } from './pages/TranscriptPage';
import { PreviewFlowHarness, PREVIEW_TOKEN } from './previewHarness';
import './index.css';
import './interaction.ts';

createRoot(document.getElementById('root')!).render(
  <PreviewFlowHarness>
    <TranscriptFlow accessToken={PREVIEW_TOKEN} />
  </PreviewFlowHarness>,
);
