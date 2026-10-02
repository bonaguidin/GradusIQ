// Resolves what a Supabase session actually has behind it, and provisions the
// two rows a confirmed sign-up needs.
//
// WHY NO NEW BACKEND ENDPOINT: the inserts run through the browser's own
// session-scoped Supabase client (publishable key + the user's JWT), which is
// byte-for-byte the same identity the backend uses -- GradusIQ_career/
// supabase_client.py builds its client from the publishable key and the
// caller's bearer token too, deliberately never the secret key. Both inserts
// were exercised against the live database under a real non-admin session
// token in the audit preceding this task and both succeeded, with a spoofed
// auth_user_id correctly rejected by `students_owner_all`'s WITH CHECK
// (42501). So a backend route would add a hop without adding authority.
//
// READ path stays on the existing GET /api/v2/student/me/profile: it is what
// defines "a students row exists" for the rest of the app, it is already
// proxied (frontend/vercel.json -> target=me-profile, the one target family
// that forwards Authorization), and reusing it means provisioning and the
// dashboard agree on the same answer.

import { supabase } from './supabase';
import { readSignupMetadata } from './signupRules.mjs';
import type { SignupMetadata } from './signupRules.mjs';
import type { MeProfile } from '../types/studentIntelligenceProfile';

const ME_PROFILE_URL = '/api/v2/student/me/profile';

/** PostgreSQL unique_violation. Means "already provisioned", not "failed". */
const UNIQUE_VIOLATION = '23505';

export type StudentAccountStatus =
  /** No Supabase session at all. */
  | 'no-session'
  /** A session exists; the students-row question is still outstanding. */
  | 'checking'
  /** A students row is confirmed present. Safe to render the dashboard. */
  | 'ready'
  /** Session with no students row and no sign-up metadata to build one from. */
  | 'absent'
  /** Provisioning was attempted and failed in a way a reload will not fix. */
  | 'error';

export interface StudentAccountState {
  status: StudentAccountStatus;
  profile: MeProfile | null;
  message: string | null;
}

export const NO_SESSION_STATE: StudentAccountState = {
  status: 'no-session',
  profile: null,
  message: null,
};

export const CHECKING_STATE: StudentAccountState = {
  status: 'checking',
  profile: null,
  message: null,
};

interface MeProfileResponse {
  status: number;
  profile: MeProfile | null;
}

async function fetchMeProfile(accessToken: string): Promise<MeProfileResponse> {
  const response = await fetch(ME_PROFILE_URL, {
    method: 'GET',
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${accessToken}`,
    },
  });

  if (response.status !== 200) {
    // The body is discarded on every non-200 today, which is exactly the
    // detail needed to tell a proxy misroute (HTML back from the SPA
    // catch-all rewrite) from a genuine backend 404/401/502. Read it here
    // purely to log it; the returned shape is unchanged.
    let body: string;
    try {
      body = await response.text();
    } catch (err) {
      body = `<unreadable: ${String(err)}>`;
    }
    console.error(
      '[studentAccount] fetchMeProfile non-200 | status:',
      response.status,
      '| content-type:',
      response.headers.get('content-type'),
      '| body:',
      body.slice(0, 600),
    );
    return { status: response.status, profile: null };
  }
  return { status: 200, profile: (await response.json()) as MeProfile };
}

function errorCode(error: unknown): string | null {
  if (error && typeof error === 'object' && 'code' in error) {
    const { code } = error as { code?: unknown };
    return typeof code === 'string' ? code : null;
  }
  return null;
}

/**
 * Insert the students row and return its id.
 *
 * `students.auth_user_id` carries a live UNIQUE constraint
 * (students_auth_user_id_key -- verified against the live database, a second
 * insert for the same user returns 23505), so this cannot create a duplicate
 * student even if it runs twice concurrently. A 23505 therefore means the row
 * is already there, which is a success for our purposes: we select it and
 * carry on. That is what makes the whole function safe to re-enter on reload,
 * on a StrictMode double-effect, or in a second browser tab.
 *
 * There is no date_of_birth column on `students`; the schema has none. The
 * value stays in user_metadata, where sign-up wrote it, and is used only as
 * part of the "did a sign-up happen" signal.
 */
async function insertStudentRow(userId: string, metadata: SignupMetadata): Promise<string> {
  const { data, error } = await supabase
    .from('students')
    .insert({ auth_user_id: userId, name: metadata.name })
    .select('id')
    .single();

  if (!error && data) {
    console.log('[studentAccount] students INSERT ok | id:', (data as { id: string }).id);
    return (data as { id: string }).id;
  }

  if (error && errorCode(error) !== UNIQUE_VIOLATION) {
    // `throw new Error(error.message)` below flattens the Supabase error to a
    // bare string, so the code/details/hint -- the parts that distinguish an
    // RLS denial (42501) from a constraint or a network failure -- never
    // reach the catch in resolveStudentAccount. Log the object intact first.
    console.error(
      '[studentAccount] students INSERT FAILED | code:',
      errorCode(error),
      '| message:',
      error.message,
      '| details:',
      (error as { details?: unknown }).details,
      '| hint:',
      (error as { hint?: unknown }).hint,
      '| full error object:',
      error,
    );
    throw new Error(error.message);
  }

  // 23505: the row exists already. Read it back rather than failing.
  console.log('[studentAccount] students INSERT hit 23505 (already provisioned); reading back.');
  const existing = await supabase.from('students').select('id').eq('auth_user_id', userId).single();
  if (existing.error || !existing.data) {
    // Insert reported "already exists" but the row is not visible to this
    // session -- an RLS-visibility mismatch rather than a write failure.
    console.error(
      '[studentAccount] students READ-BACK FAILED after 23505 | code:',
      errorCode(existing.error),
      '| full error object:',
      existing.error,
      '| data:',
      existing.data,
    );
    throw new Error(existing.error?.message ?? 'Could not read back your student record.');
  }
  return (existing.data as { id: string }).id;
}

/**
 * Insert the home student_institutions row, tolerating "already there".
 *
 * `student_institutions_one_home_per_student` is a live partial unique index on
 * (student_id) WHERE relationship = 'home' (verified: a second home insert
 * returns 23505), so a student can never end up with two homes and a repeat
 * call is a no-op rather than a corruption.
 */
async function ensureHomeInstitution(studentId: string, institutionId: string): Promise<void> {
  const { error } = await supabase.from('student_institutions').insert({
    student_id: studentId,
    institution_id: institutionId,
    relationship: 'home',
  });

  if (error && errorCode(error) !== UNIQUE_VIOLATION) {
    // Same flattening problem as the students insert above.
    console.error(
      '[studentAccount] student_institutions INSERT FAILED | code:',
      errorCode(error),
      '| message:',
      error.message,
      '| details:',
      (error as { details?: unknown }).details,
      '| hint:',
      (error as { hint?: unknown }).hint,
      '| studentId:',
      studentId,
      '| institutionId:',
      institutionId,
      '| full error object:',
      error,
    );
    throw new Error(error.message);
  }
  console.log(
    '[studentAccount] student_institutions ensured | studentId:',
    studentId,
    '| institutionId:',
    institutionId,
    '| duplicate:',
    error ? '23505 (already present)' : 'no (inserted)',
  );
}

function failed(message: string): StudentAccountState {
  return { status: 'error', profile: null, message };
}

/**
 * THE PARTIAL-FAILURE CASE, handled explicitly.
 *
 * The two inserts are separate statements, so "students written,
 * student_institutions not" is reachable -- a closed tab or a dropped
 * connection between them is enough, and the live audit confirmed each insert
 * is independently attemptable.
 *
 * The detection signal is NOT /api/v2/student/me/gpa's 409, even though the
 * route is reachable (proxied as me-gpa) -- nothing in this codebase actually
 * calls it today. It is not needed here either way: profile_builder.py's
 * _resolve_institution_name returns None instead of raising where the GPA route
 * raises 409, so a half-provisioned student comes back from /me/profile as a
 * plain HTTP 200 whose `student.institution` is null. Confirmed by running
 * build_profile_from_supabase against a live students row with no home
 * institution: 200-equivalent, institution=None, no exception.
 *
 * So: 200 + null institution == the second insert is outstanding. We complete
 * just that piece, using the institution_id still sitting in user_metadata, and
 * re-read to confirm. Nothing re-inserts the students row, and the unique index
 * makes a redundant attempt a no-op regardless.
 */
async function repairMissingInstitution(
  profile: MeProfile,
  accessToken: string,
  metadata: SignupMetadata,
): Promise<StudentAccountState> {
  console.log(
    '[studentAccount] repairMissingInstitution: linking institution',
    metadata.institutionId,
    'to studentId',
    profile.student.id,
  );
  try {
    await ensureHomeInstitution(profile.student.id, metadata.institutionId);
  } catch (err) {
    console.error('[studentAccount] BRANCH: error -- repair insert threw | flattened:', err);
    return failed(
      err instanceof Error
        ? `Your account exists but its institution could not be linked: ${err.message}`
        : 'Your account exists but its institution could not be linked.',
    );
  }

  const confirmed = await fetchMeProfile(accessToken);
  if (confirmed.status === 200 && confirmed.profile) {
    console.log(
      '[studentAccount] BRANCH: ready -- repair completed | institution:',
      confirmed.profile.student.institution,
    );
    return { status: 'ready', profile: confirmed.profile, message: null };
  }
  console.error(
    '[studentAccount] BRANCH: error -- repair wrote the link but re-read failed | status:',
    confirmed.status,
  );
  return failed('Your institution was linked but your profile could not be re-read.');
}

/**
 * Decide the account state for a session, provisioning if (and only if) this is
 * a confirmed sign-up that has not been provisioned yet.
 *
 * `userMetadata` is `user.user_metadata` from the session.
 */
export async function resolveStudentAccount(
  accessToken: string,
  userId: string,
  userMetadata: unknown,
): Promise<StudentAccountState> {
  const metadata = readSignupMetadata(userMetadata);

  console.log(
    '[studentAccount] resolveStudentAccount ENTER | userId:',
    userId,
    '| accessToken:',
    accessToken ? `present (len ${String(accessToken.length)})` : 'ABSENT',
    '| signup metadata parsed:',
    metadata ? metadata : 'null (readSignupMetadata rejected user_metadata)',
  );

  let current: MeProfileResponse;
  try {
    current = await fetchMeProfile(accessToken);
  } catch (err) {
    // Empty catch today: a DNS failure, CORS rejection or offline network is
    // indistinguishable from any other fetch problem. Still swallowed below.
    console.error(
      '[studentAccount] fetchMeProfile THREW (network/CORS, not an HTTP status) | error:',
      err,
    );
    return failed('Could not reach the server to load your profile. Check your connection.');
  }

  console.log('[studentAccount] /me/profile status:', current.status);

  if (current.status === 200 && current.profile) {
    if (current.profile.student.institution !== null) {
      console.log(
        '[studentAccount] BRANCH: ready -- students row exists with institution',
        current.profile.student.institution,
        '| studentId:',
        current.profile.student.id,
      );
      return { status: 'ready', profile: current.profile, message: null };
    }
    console.warn(
      '[studentAccount] 200 but institution is null -- half-provisioned student.',
      '| studentId:',
      current.profile.student.id,
      '| repairable:',
      metadata ? 'yes (metadata present)' : 'no (no metadata)',
    );
    // A students row with no home institution. If a sign-up is behind this
    // session, that is the half-written state above and we finish it.
    if (metadata) {
      return repairMissingInstitution(current.profile, accessToken, metadata);
    }
    // No metadata to repair from, and guessing an institution is exactly what
    // must not happen. This is not treated as an error: the backend itself
    // regards a student with no home institution as a valid, analyzable
    // profile (_resolve_institution_name degrades to null by design rather
    // than raising), so locking such a student out of the dashboard would
    // invent a failure the rest of the system does not recognize.
    console.warn(
      '[studentAccount] BRANCH: ready -- institution null and no metadata to repair from.',
    );
    return { status: 'ready', profile: current.profile, message: null };
  }

  if (current.status === 404) {
    // No students row. Either the first session after a sign-up (which is the
    // signUp() call itself when email confirmation is disabled, or the first
    // login after confirming when it is enabled), or a session with no student
    // behind it.
    if (!metadata) {
      // 404 + no usable metadata: provisioning is never even attempted. For a
      // real sign-up this means readSignupMetadata rejected user_metadata.
      console.error(
        '[studentAccount] BRANCH: absent -- /me/profile 404 and no sign-up metadata,',
        'so NO INSERT IS ATTEMPTED. Raw user_metadata was:',
        userMetadata,
      );
      return {
        status: 'absent',
        profile: null,
        message:
          'This account is signed in but has no student profile, and there is no sign-up ' +
          'information attached to it to build one from.',
      };
    }

    console.log('[studentAccount] 404 + metadata present -> attempting provisioning inserts.');

    let studentId: string;
    try {
      studentId = await insertStudentRow(userId, metadata);
    } catch (err) {
      console.error(
        '[studentAccount] BRANCH: error -- students insert threw.',
        'See the "students INSERT FAILED" line above for the raw Postgres error.',
        '| flattened:',
        err,
      );
      return failed(
        err instanceof Error
          ? `Your student profile could not be created: ${err.message}`
          : 'Your student profile could not be created.',
      );
    }

    try {
      await ensureHomeInstitution(studentId, metadata.institutionId);
    } catch (err) {
      console.error(
        '[studentAccount] BRANCH: error -- student_institutions insert threw',
        'AFTER the students row was written (half-provisioned).',
        '| studentId:',
        studentId,
        '| flattened:',
        err,
      );
      // The students row IS written. Deliberately not rolled back: the next
      // load re-enters here, /me/profile now answers 200 with a null
      // institution, and repairMissingInstitution() completes just this piece.
      return failed(
        err instanceof Error
          ? `Your profile was created but its institution could not be linked: ${err.message}. ` +
            'Reloading will finish the remaining step.'
          : 'Your profile was created but its institution could not be linked. ' +
            'Reloading will finish the remaining step.',
      );
    }

    // Refetch once to confirm what was actually written, rather than assuming.
    let confirmed: MeProfileResponse;
    try {
      confirmed = await fetchMeProfile(accessToken);
    } catch (err) {
      // Empty catch today.
      console.error(
        '[studentAccount] BRANCH: error -- post-insert re-read THREW.',
        'Both inserts reported success but the row could not be confirmed.',
        '| studentId:',
        studentId,
        '| error:',
        err,
      );
      return failed('Your profile was created but could not be loaded. Try reloading.');
    }
    if (confirmed.status === 200 && confirmed.profile) {
      console.log(
        '[studentAccount] BRANCH: ready -- provisioning completed and verified | studentId:',
        confirmed.profile.student.id,
        '| institution:',
        confirmed.profile.student.institution,
      );
      return { status: 'ready', profile: confirmed.profile, message: null };
    }
    // Inserts reported success, yet /me/profile still cannot see the row.
    console.error(
      '[studentAccount] BRANCH: error -- INSERTS SUCCEEDED BUT ROW IS ABSENT afterward.',
      'Post-insert /me/profile status:',
      confirmed.status,
      '| studentId returned by insert:',
      studentId,
      '(see the fetchMeProfile non-200 line above for the body)',
    );
    return failed(
      `Your profile was created but could not be loaded (status ${String(confirmed.status)}).`,
    );
  }

  if (current.status === 401) {
    console.error(
      '[studentAccount] BRANCH: error -- /me/profile returned 401.',
      'The bearer token was rejected; no provisioning was attempted.',
    );
    return failed('Your session could not be verified. Sign in again.');
  }

  // Any status that is neither 200, 404 nor 401 -- e.g. a 502 from the proxy,
  // or a 200-with-HTML from the SPA catch-all rewrite if the rewrite is
  // missing in the deployed environment.
  console.error(
    '[studentAccount] BRANCH: error -- /me/profile returned an unexpected status:',
    current.status,
    '(not 200/404/401). No provisioning was attempted.',
    'See the fetchMeProfile non-200 line above for the response body.',
  );
  return failed(`Your profile could not be loaded (status ${String(current.status)}).`);
}

// StrictMode double-invokes effects in development, and a token refresh can
// re-enter this path too. The DB constraints already make a double run
// harmless; sharing the in-flight promise keeps it from being wasteful and
// keeps the two runs from racing to set contradictory state.
const inFlight = new Map<string, Promise<StudentAccountState>>();

export function resolveStudentAccountOnce(
  accessToken: string,
  userId: string,
  userMetadata: unknown,
): Promise<StudentAccountState> {
  const existing = inFlight.get(userId);
  if (existing) {
    console.log(
      '[studentAccount] resolveStudentAccountOnce: reusing in-flight run for userId',
      userId,
      '(this call did not start a new resolution).',
    );
    return existing;
  }

  const run = resolveStudentAccount(accessToken, userId, userMetadata).finally(() => {
    inFlight.delete(userId);
  });
  inFlight.set(userId, run);
  return run;
}
