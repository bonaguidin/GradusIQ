export const TOUR_COMPLETED_METADATA_KEY: string;
export function tourSeenStorageKey(userId: string): string;
export function tourCompletedOnAccount(userMetadata: Record<string, unknown> | null | undefined): boolean;
export function shouldAutoOpenTour(input: {
  userMetadata: Record<string, unknown> | null | undefined;
  seenInBrowser: boolean;
}): boolean;
export function needsAccountBackfill(input: {
  userMetadata: Record<string, unknown> | null | undefined;
  seenInBrowser: boolean;
}): boolean;
