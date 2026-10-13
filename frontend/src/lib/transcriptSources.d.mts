export interface TranscriptSource {
  portalName: string;
  portalUrl: string;
  steps: string[];
  source: string;
}

export const GENERIC_TRANSCRIPT_STEPS: string[];
export function transcriptSourceFor(institutionName: string | null | undefined): TranscriptSource | null;
export function isAcceptedTranscriptFile(name: string | null | undefined): boolean;
