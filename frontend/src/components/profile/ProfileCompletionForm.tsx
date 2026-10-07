import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useErrorFocus } from '../../hooks/useErrorFocus';
import { updateProfile, type ProfileChanges } from '../../api/profile';
import type { MissingField } from '../../types/analysis';
import type { StudentIntelligenceProfile } from '../../types/studentIntelligenceProfile';
import { TagInput } from '../TagInput';
import { TargetRolesEditor } from '../TargetRolesEditor';
import { AiComfortOptions, aiComfortChanges } from './fields/AiComfortField';
import {
  GraduationInputs,
  graduationChanges,
  graduationValueFrom,
  validateGraduation,
  type GraduationValue,
} from './fields/GraduationField';
import {
  MajorInputs,
  majorChanges,
  majorValueFrom,
  validateMajor,
  type MajorValue,
} from './fields/MajorField';

interface Props {
  profile: StudentIntelligenceProfile;
  accessToken: string;
  missingFields?: MissingField[];
  feature?: string;
  onCancel(): void;
  onSaved(): Promise<void>;
  onSavingChange?(saving: boolean): void;
}

const HELP: Record<string, string> = {
  'student.major_intended': 'Required for FIT. Tick the box above if you are planning to switch majors.',
  'student.expected_graduation': 'Required for GAP so guidance matches your timeline.',
  'career.target_roles': 'Add at least one target role to run this analysis.',
  'career.interests': 'Add at least one career interest to run FIT.',
  'career.ai_anxiety_level': 'Optional context for how guidance discusses AI.',
};

/**
 * The batch host for the same fields the Career tab now edits inline.
 *
 * COMPOSED FROM THE FIELD COMPONENTS, NOT A SECOND COPY OF THEM. The switching
 * checkbox and its sentinel write, the season/year pair and its both-or-neither
 * rule, and the AI radio group all live in ./fields and are rendered here
 * exactly as the inline rows render them. What stays here is only what a batch
 * form owns and an inline field does not: the diff against the loaded profile,
 * the per-field "this is why the analysis wants it" copy, and one submit that
 * writes every changed key at once.
 *
 * This surface is not retired. /profile/complete is still the deep-link target
 * for a missing field, and a student who lands there should be able to answer
 * several at once rather than saving four times.
 */
export function ProfileCompletionForm({ profile, accessToken, missingFields = [], feature, onCancel, onSaved, onSavingChange }: Props) {
  const storedIntended = profile.academics.summary.major_intended ?? '';
  const storedGraduation = profile.identity.expected_graduation;
  const initial = useMemo(() => ({
    classification: profile.identity.classification ?? '',
    majorCurrent: profile.academics.summary.major_current ?? '',
    major: majorValueFrom(storedIntended),
    graduation: graduationValueFrom(storedGraduation),
    targetRoles: profile.career.target_roles,
    interests: profile.career.interests,
    anxiety: profile.career.ai_anxiety_level ?? '',
  }), [profile, storedIntended, storedGraduation]);
  const [classification, setClassification] = useState(initial.classification);
  const [majorCurrent, setMajorCurrent] = useState(initial.majorCurrent);
  const [major, setMajor] = useState<MajorValue>(initial.major);
  const [graduation, setGraduation] = useState<GraduationValue>(initial.graduation);
  const [targetRoles, setTargetRoles] = useState(initial.targetRoles);
  const [interests, setInterests] = useState(initial.interests);
  const [anxiety, setAnxiety] = useState(initial.anxiety);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [failure, setFailure] = useState<string | null>(null);
  const missing = new Set(missingFields.map((field) => field.path));

  // One ref per field that validate() can fail, in the same order they
  // appear in the form. On a failed validate(), focus goes to whichever
  // of these is first with an error -- there is no single error message
  // to point to here the way the other auth/onboarding forms have, since
  // several fields can be invalid independently.
  const majorRef = useRef<HTMLDivElement>(null);
  const graduationRef = useRef<HTMLDivElement>(null);
  const targetRolesRef = useRef<HTMLDivElement>(null);
  const interestsRef = useRef<HTMLDivElement>(null);
  const failureRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    const order: Array<[string, typeof majorRef]> = [
      ['student.major_intended', majorRef],
      ['student.expected_graduation', graduationRef],
      ['career.target_roles', targetRolesRef],
      ['career.interests', interestsRef],
    ];
    order.find(([path]) => errors[path])?.[1].current?.focus();
  }, [errors]);
  useErrorFocus(failure, failureRef);

  function validate() {
    const next: Record<string, string> = {};
    // The field components own their own rules; the form only decides which of
    // its gaps an analysis is currently blocked on.
    const majorInvalid = validateMajor(major);
    if (majorInvalid) next['student.major_intended'] = majorInvalid;
    if (missing.has('career.target_roles') && targetRoles.length === 0) next['career.target_roles'] = HELP['career.target_roles'];
    if (missing.has('career.interests') && interests.length === 0) next['career.interests'] = HELP['career.interests'];
    if (missing.has('student.expected_graduation') && (!graduation.season || !graduation.year)) next['student.expected_graduation'] = HELP['student.expected_graduation'];
    const graduationInvalid = validateGraduation(graduation);
    if (graduationInvalid) next['student.expected_graduation'] = graduationInvalid;
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!validate()) return;
    const changes: ProfileChanges = {
      // Each field states its own change, so the sentinel, the joined
      // graduation string and the null-vs-'not_sure' distinction are decided
      // in one place for both hosts.
      ...majorChanges(major, storedIntended),
      ...graduationChanges(graduation, storedGraduation),
      ...aiComfortChanges(anxiety, initial.anxiety),
    };
    if (classification.trim() !== initial.classification) changes.classification = classification.trim();
    if (majorCurrent.trim() !== initial.majorCurrent) changes.major_current = majorCurrent.trim();
    if (JSON.stringify(targetRoles) !== JSON.stringify(initial.targetRoles)) changes.target_roles = targetRoles;
    if (JSON.stringify(interests) !== JSON.stringify(initial.interests)) changes.interests = interests;
    setSaving(true); onSavingChange?.(true); setFailure(null);
    try {
      if (Object.keys(changes).length > 0) await updateProfile(accessToken, changes);
      await onSaved();
    } catch (error) {
      setFailure(error instanceof Error ? error.message : 'Your profile could not be saved.');
    } finally {
      setSaving(false); onSavingChange?.(false);
    }
  }

  const fieldClass = (path: string) => `profile-form-field${missing.has(path) ? ' profile-form-field--needed' : ''}`;
  const helper = (path: string) => errors[path] ?? (missing.has(path) ? HELP[path] : null);
  return (
    <form className="profile-completion-form" onSubmit={(event) => { void submit(event); }} noValidate>
      {feature && missingFields.length > 0 && <p className="profile-context"><strong>{missingFields.length} {missingFields.length === 1 ? 'detail' : 'details'} needed for {feature}</strong></p>}

      <section className="profile-form-section">
        <h3 className="editable-section-title">Academic</h3>
        <div className="profile-form-grid">
          <label>Classification<input value={classification} onChange={(e) => setClassification(e.target.value)} /></label>
          <label>Current major<input value={majorCurrent} onChange={(e) => setMajorCurrent(e.target.value)} /></label>
        </div>
        <div className={missing.has('student.major_intended') ? 'profile-form-field--needed' : undefined} tabIndex={-1} ref={majorRef}>
          <MajorInputs value={major} onChange={setMajor} helper={helper('student.major_intended')} idPrefix="form-major" />
        </div>
        <div className={fieldClass('student.expected_graduation')} tabIndex={-1} ref={graduationRef}>
          <span className="form-label">Expected graduation</span>
          <GraduationInputs value={graduation} onChange={setGraduation} />
          {helper('student.expected_graduation') && <small>{helper('student.expected_graduation')}</small>}
        </div>
      </section>

      <section className="profile-form-section">
        <h3 className="editable-section-title">Career direction</h3>
        <div className={fieldClass('career.target_roles')} tabIndex={-1} ref={targetRolesRef}><TargetRolesEditor roles={targetRoles} isEditing onChange={setTargetRoles} />{helper('career.target_roles') && <small>{helper('career.target_roles')}</small>}</div>
        <div className={fieldClass('career.interests')} tabIndex={-1} ref={interestsRef}><TagInput label="Career interests" value={interests} onChange={setInterests} placeholder="Add interest" />{helper('career.interests') && <small>{helper('career.interests')}</small>}</div>
      </section>

      <section className="profile-form-section">
        <h3 className="editable-section-title">AI comfort</h3>
        <AiComfortOptions value={anxiety} onChange={setAnxiety} name="ai-comfort" />
      </section>

      {/* Skills and experience are owned by the resume review screen, which
          parses them from the uploaded document. This surface used to offer a
          second, competing place to type them; it now says where they live. */}
      <p className="profile-form-note"><span className="profile-form-note-icon" aria-hidden="true">ⓘ</span><span>Skills and work experience are edited in <Link to="/resume">resume review</Link>.</span></p>

      {failure && <p className="profile-form-error" role="alert" tabIndex={-1} ref={failureRef}>{failure}</p>}
      <div className="profile-form-actions"><button type="button" className="btn btn-ghost" onClick={onCancel} disabled={saving}>Cancel</button><button type="submit" className="btn btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save changes'}</button></div>
    </form>
  );
}
