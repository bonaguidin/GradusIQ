// Whether the first-run onboarding tour should open on its own.
//
// Completion lives in the user's Supabase `user_metadata` so it follows the
// account to every browser, device and deploy URL. localStorage alone was
// per-origin: each new browser, private window or Vercel preview URL looked
// like a first visit, so the tour kept reopening after it had been finished.
// The old localStorage flag is still honoured (and copied up to the account)
// so anyone who finished the tour before this change is not shown it again.

export const TOUR_COMPLETED_METADATA_KEY = 'onboarding_tour_completed_at';

const TOUR_SEEN_PREFIX = 'gradusiq_tour_seen_';

/** localStorage key for the per-browser copy of the flag. */
export function tourSeenStorageKey(userId) {
  return `${TOUR_SEEN_PREFIX}${userId}`;
}

/** True when the account itself records a finished (or skipped) tour. */
export function tourCompletedOnAccount(userMetadata) {
  return Boolean(userMetadata && userMetadata[TOUR_COMPLETED_METADATA_KEY]);
}

/** Auto-open only when neither the account nor this browser has seen it. */
export function shouldAutoOpenTour({ userMetadata, seenInBrowser }) {
  return !tourCompletedOnAccount(userMetadata) && !seenInBrowser;
}

/** This browser saw the tour before completion moved to the account. */
export function needsAccountBackfill({ userMetadata, seenInBrowser }) {
  return Boolean(seenInBrowser) && !tourCompletedOnAccount(userMetadata);
}
