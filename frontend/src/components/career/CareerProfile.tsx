import { useEffect, useRef, type ReactNode } from 'react';
import type { ProfileChanges } from '../../api/profile';
import { revealField } from '../../lib/revealField';
import { buildCareerViewModel } from '../../data/careerViewModel.mjs';
import type { CanonicalCareer } from '../../types/studentIntelligenceProfile';
import type { CertificationEntry, ExperienceEntry } from '../../data/careerViewModel.mjs';
import { InterestsEditor } from '../InterestsEditor';
import { TargetRolesEditor } from '../TargetRolesEditor';
import { useSupportedTargetRoles } from '../../hooks/useSupportedTargetRoles';
import { AiComfortField, aiComfortChanges, aiComfortLabel } from '../profile/fields/AiComfortField';
import {
  GraduationInputs,
  graduationChanges,
  graduationValueFrom,
  validateGraduation,
} from '../profile/fields/GraduationField';
import { InlineEditableField } from '../profile/fields/InlineEditableField';
import {
  CurrentMajorInput,
  MajorInputs,
  majorChanges,
  majorCurrentChanges,
  majorValueFrom,
  validateMajor,
} from '../profile/fields/MajorField';
import { ProjectCard } from './ProjectCard';
import { SkillCloud } from './SkillCloud';
import { TagInput } from '../TagInput';

/**
 * What a field needs to save itself, or null when nothing here can be edited.
 *
 * Null is the honest state for a session with no bearer token and no demo
 * identity: without either, a change has nowhere to go, so no Edit button is
 * rendered rather than one that would fail. The page falls back to exactly
 * the read-only surface it had.
 *
 * `persist` is the one seam between an authenticated save (a real PATCH to
 * /me/profile) and a demo save (a local-only merge, never sent anywhere) --
 * everything else in this file and its children is identical either way.
 */
export interface CareerEditing {
  persist(changes: ProfileChanges): Promise<void>;
  onSaved(): Promise<void>;
}

/**
 * A standing request to go and answer one field.
 *
 * The nonce, not the path, is what makes the field react: asking twice for the
 * same field has to work, and a path compared against its previous value would
 * treat the second click as no change at all.
 */
export interface CareerFieldFocus {
  path: string;
  nonce: number;
}

/**
 * Whether a tag list is unchanged, so an untouched field spends no request.
 *
 * Order is significant: these are the student's own ordering, and reordering
 * them is an edit like any other.
 */
function sameList(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((entry, index) => entry === b[index]);
}

/** The two student-editable skill lists, saved as skills_technical / skills_soft. */
interface SkillLists {
  technical: string[];
  soft: string[];
}

/** Only the lists that changed, so an untouched one is not rewritten. */
function skillsChanges(draft: SkillLists, saved: SkillLists): ProfileChanges {
  const changes: ProfileChanges = {};
  if (!sameList(draft.technical, saved.technical)) changes.skills_technical = draft.technical;
  if (!sameList(draft.soft, saved.soft)) changes.skills_soft = draft.soft;
  return changes;
}

/**
 * The identity facts the Career tab reports but does not own.
 *
 * Expected graduation and the majors live on `identity` and
 * `academics.summary`, not on `career` -- they are academic record, and this
 * component is not going to reach across the profile to find them. The
 * dashboard already holds all three (see dashboardViewModel) and hands them
 * down, so this stays a props-in component and no new fetch exists anywhere.
 */
export interface CareerDetails {
  expectedGraduation: string | null;
  majorCurrent: string | null;
  majorIntended: string | null;
}

/**
 * The authenticated Career profile.
 *
 * WHAT THIS REPLACED AND WHY. Five equal cards in a rigid two-column grid, each
 * a fixed-height rectangle regardless of what it held: skills as one
 * comma-separated paragraph, experience as employer/role database rows,
 * projects as whole résumé descriptions pasted in, and three sibling sentences
 * ("No career goal provided." / "No target roles provided." / "No interests
 * provided.") occupying a full card to say nothing was there. The layout gave
 * a 300-word project and an empty certifications list identical space.
 *
 * The hierarchy now follows information weight rather than the grid: a compact
 * summary strip, then direction beside skills (direction is short, skills are
 * long, so they are not the same width), then experience beside certifications,
 * then projects across the full measure because they hold the most text.
 *
 * EMPTY SECTIONS COLLAPSE TO A LINE. An absence is worth one sentence, not a
 * rectangle. Student-declared direction fields edit here in place; evidence
 * sections simply report what the canonical profile currently contains.
 */
export function CareerProfile({
  career,
  details,
  editing = null,
  focus = null,
}: {
  career: CanonicalCareer;
  details: CareerDetails;
  editing?: CareerEditing | null;
  focus?: CareerFieldFocus | null;
}) {
  const model = buildCareerViewModel(career);
  const { direction, counts } = model;
  const supportedRoles = useSupportedTargetRoles();
  const skillLists: SkillLists = { technical: career.skills.technical, soft: career.skills.soft };

  // The read-only renderings, named once so the editable and read-only paths
  // cannot drift into showing two different things for the same data.
  const rolesDisplay = direction.hasTargetRoles ? (
    <ul className="cp-roles">
      {direction.targetRoles.map((role) => (
        <li key={role}>
          {role}
          {supportedRoles !== null && !supportedRoles.includes(role) && (
            <span className="course-discovery-status-badge course-discovery-status-badge--verify cp-role-coverage-badge">
              Analysis coverage unavailable
            </span>
          )}
        </li>
      ))}
    </ul>
  ) : (
    <Absence
      line="No target roles added yet."
      help="Add the roles you're interested in so FIT, GAP and SHIFT can personalize guidance."
    />
  );
  const interestsDisplay = direction.hasInterests ? (
    <p className="cp-inline-list">{direction.interests.join(' · ')}</p>
  ) : (
    <Absence line="No interests added yet." />
  );

  return (
    <div className="cp">
      <CareerSummary model={model} />

      <DetailsSection
        details={details}
        aiComfort={career.ai_anxiety_level}
        editing={editing}
        focus={focus}
      />

      {/* Career direction is its own full-width band -- it no longer shares a
          row (and competes for column width) with Skills, which needs the
          full measure for however many chips it holds. Target roles and
          interests sit side-by-side WITHIN this band, in a 2-column sub-grid,
          since they are the two fields every analysis actually reads. */}
      <Section title="Career direction" count={null}>
        <div className="cp-direction">
          {/* TargetRolesEditor and InterestsEditor are reused unchanged, but
              only for the editing half. Their read-only half renders chips,
              and this page states roles as a list and interests as one line
              -- so the display above stands and the editors supply the input
              surface they were written for. */}
          <div className="cp-direction-grid">
            <FieldSlot
              label="Target roles"
              path="career.target_roles"
              focus={focus}
              wrapperClass="cp-field"
              labelClass="cp-subhead"
              editing={editing}
              editLabel={direction.hasTargetRoles ? 'Edit' : 'Add target roles'}
              value={direction.targetRoles}
              toChanges={(roles) => (sameList(roles, direction.targetRoles) ? {} : { target_roles: roles })}
              display={rolesDisplay}
              edit={(draft, setDraft) => (
                <TargetRolesEditor roles={draft} isEditing onChange={setDraft} />
              )}
            />
            <FieldSlot
              label="Interests"
              path="career.interests"
              focus={focus}
              wrapperClass="cp-field"
              labelClass="cp-subhead"
              editing={editing}
              value={direction.interests}
              toChanges={(interests) => (sameList(interests, direction.interests) ? {} : { interests })}
              display={interestsDisplay}
              edit={(draft, setDraft) => (
                <InterestsEditor interests={draft} isEditing onChange={setDraft} />
              )}
            />
          </div>
          {/* Goals and location keep the treatment they had: present or
              silent. Neither is required by any analysis, so neither earns
              an absence line arguing for itself. */}
          {direction.goals && (
            <div className="cp-field">
              <h4 className="cp-subhead">Goal</h4>
              <p className="cp-prose">{direction.goals}</p>
            </div>
          )}
          {direction.location && (
            <div className="cp-field">
              <h4 className="cp-subhead">Location preference</h4>
              <p className="cp-prose">{direction.location}</p>
            </div>
          )}
        </div>
      </Section>

      {/* Skills is its own full-width band, not a sidebar column -- the
          "Show 30 more" expand-in-place behaviour inside SkillCloud is
          untouched, only the outer container changed. */}
      <Section title="Skills" count={counts.skills}>
        <FieldSlot
          label="Technical and soft skills"
          path="career.skills"
          focus={focus}
          wrapperClass="cp-field"
          labelClass="cp-subhead"
          editing={editing}
          editLabel={counts.skills > 0 ? 'Edit' : 'Add skills'}
          value={skillLists}
          toChanges={(draft) => skillsChanges(draft, skillLists)}
          display={
            counts.skills > 0 ? (
              <SkillCloud groups={model.skillGroups} total={counts.skills} />
            ) : (
              <Absence line="No skills confirmed yet." />
            )
          }
          edit={(draft, setDraft) => (
            <div className="cp-skills-edit">
              <TagInput
                label="Technical skills"
                value={draft.technical}
                onChange={(technical) => setDraft({ ...draft, technical })}
                placeholder="Add a skill and press Enter…"
              />
              <TagInput
                label="Soft skills"
                value={draft.soft}
                onChange={(soft) => setDraft({ ...draft, soft })}
                placeholder="Add a skill and press Enter…"
              />
            </div>
          )}
        />
      </Section>

      {/* Experience: full-width vertical list, not a half-width column. */}
      <Section title="Experience" count={counts.experience}>
        {counts.experience > 0 ? (
          <ol className="cp-timeline">
            {model.experience.map((entry) => (
              <ExperienceRow entry={entry} key={entry.key} />
            ))}
          </ol>
        ) : (
          <Absence line="No experience confirmed yet." />
        )}
      </Section>

      {/* Certifications: full-width horizontal row of compact cards, not a
          tall sidebar column sitting next to Experience with dead space
          beside it. */}
      <Section title="Certifications" count={counts.certifications}>
        {counts.certifications > 0 ? (
          <ul className="cp-certs">
            {model.certifications.map((entry) => (
              <CertificationRow entry={entry} key={entry.key} />
            ))}
          </ul>
        ) : (
          <Absence line="No certifications yet." />
        )}
      </Section>

      <Section title="Projects" count={counts.projects}>
        {counts.projects > 0 ? (
          <div className="cp-projects">
            {model.projects.map((project) => (
              <ProjectCard project={project} key={project.key} />
            ))}
          </div>
        ) : (
          <Absence line="No projects yet." />
        )}
      </Section>
    </div>
  );
}

/**
 * The orientation strip.
 *
 * Every number is `array.length` and every word is a canonical string. There is
 * no readiness score, no percentage and no ranking here, because the profile
 * contains none -- the closest thing it has is the boolean
 * `completeness.career.*` family, and a count the student can verify by
 * scrolling is more honest than a figure only we can compute.
 *
 * The student's name is deliberately absent: the dashboard rail and the
 * overview header already establish whose profile this is.
 */
function CareerSummary({ model }: { model: ReturnType<typeof buildCareerViewModel> }) {
  const { direction, counts } = model;
  const headline = direction.targetRoles.length > 0 ? direction.targetRoles.join(' · ') : null;

  return (
    <header className="cp-summary">
      {/* No "Career" eyebrow here: the topbar and the section's own <h2>
          already say it twice, and a third would be noise rather than
          orientation. */}
      <div className="cp-summary-lead">
        {headline ? (
          <p className="cp-summary-roles">{headline}</p>
        ) : (
          <p className="cp-summary-roles cp-summary-roles--absent">No target roles yet</p>
        )}
      </div>

      <dl className="cp-metrics">
        {[
          { label: counts.skills === 1 ? 'Skill' : 'Skills', value: counts.skills },
          { label: counts.experience === 1 ? 'Experience' : 'Experiences', value: counts.experience },
          { label: counts.projects === 1 ? 'Project' : 'Projects', value: counts.projects },
          {
            label: counts.certifications === 1 ? 'Certification' : 'Certifications',
            value: counts.certifications,
          },
        ].map(({ label, value }) => (
          <div className="cp-metric" key={label}>
            <dt className="cp-metric-label">{label}</dt>
            <dd className="cp-metric-value">{value}</dd>
          </div>
        ))}
      </dl>
    </header>
  );
}

/**
 * The facts guidance is calibrated against, stated plainly -- and editable
 * where the student is the one who knows them.
 *
 * These three rows exist because nothing in the authenticated app rendered
 * them at all: a student could be told an analysis needed their expected
 * graduation while the page never showed what it had. They are now also the
 * place it gets fixed, so the answer is given where the gap is stated rather
 * than in a dialog opened from somewhere else.
 *
 * A missing value is "Not set" rather than an em dash. The dash is what the
 * demo's CareerSummaryRow uses, and it reads as a layout filler -- an absence
 * has to say it is an absence.
 */
function DetailsSection({
  details,
  aiComfort,
  editing,
  focus,
}: {
  details: CareerDetails;
  aiComfort: string | null;
  editing: CareerEditing | null;
  focus: CareerFieldFocus | null;
}) {
  const { expectedGraduation, majorCurrent, majorIntended } = details;
  // The sentinel is a stored answer ("not switching"), never a major anyone
  // typed, so it must not be printed back as though it were one.
  const major = majorValueFrom(majorIntended);

  return (
    <Section title="Details" count={null}>
      <div className="cp-details">
        <FieldSlot
          label="Expected graduation"
          path="student.expected_graduation"
          focus={focus}
          wrapperClass="cp-detail"
          labelClass="cp-detail-label"
          editing={editing}
          value={graduationValueFrom(expectedGraduation)}
          validate={validateGraduation}
          toChanges={(draft) => graduationChanges(draft, expectedGraduation)}
          display={<DetailValue value={expectedGraduation} />}
          edit={(draft, setDraft) => <GraduationInputs value={draft} onChange={setDraft} />}
        />
        {/* Correcting a mis-parsed current major and deciding to switch are
            unrelated events, so they are two independent slots -- pairing
            them under one label made the first wait on the second, and made
            a student answer a question about their future to fix a typo
            about their present. Each is now its own column in the same
            4-column row as Expected Graduation and AI Comfort. */}
        <FieldSlot
          label="Current major"
          wrapperClass="cp-detail"
          labelClass="cp-detail-label"
          editing={editing}
          value={majorCurrent ?? ''}
          toChanges={(draft) => majorCurrentChanges(draft, majorCurrent)}
          display={<DetailValue value={majorCurrent} />}
          edit={(draft, setDraft) => <CurrentMajorInput value={draft} onChange={setDraft} />}
        />
        <FieldSlot
          label="Intended major"
          path="student.major_intended"
          focus={focus}
          wrapperClass="cp-detail"
          labelClass="cp-detail-label"
          editing={editing}
          value={major}
          validate={validateMajor}
          toChanges={(draft) => majorChanges(draft, majorIntended)}
          // Only a switching student has an intended major to report. "Not
          // switching majors" is a real answer, but it is the absence of a
          // second major, so it reads in the quieter absent voice rather
          // than sitting where a major name would.
          display={
            <DetailValue
              value={major.switching ? major.majorIntended : null}
              absentLabel="Not switching majors"
            />
          }
          edit={(draft, setDraft) => (
            <MajorInputs value={draft} onChange={setDraft} idPrefix="cp-major" />
          )}
        />
        <FieldSlot
          label="AI comfort"
          path="career.ai_anxiety_level"
          focus={focus}
          wrapperClass="cp-detail"
          labelClass="cp-detail-label"
          editing={editing}
          value={aiComfort ?? ''}
          toChanges={(draft) => aiComfortChanges(draft, aiComfort)}
          editLabel={aiComfort ? 'Edit' : 'Add'}
          display={<DetailValue value={aiComfortLabel(aiComfort)} absentLabel="Not answered" />}
          edit={(draft, setDraft) => (
            <AiComfortField value={draft} onChange={setDraft} name="cp-ai-comfort" />
          )}
        />
      </div>
    </Section>
  );
}

/**
 * One stored fact, or an explicit absence in its place.
 *
 * There is no longer a subordinate note here. It existed to hang the switching
 * state off the current major, which said the two were one fact and its
 * caption; they are two facts, and each is now its own editable unit with its
 * own label and its own value.
 */
function DetailValue({
  value,
  absentLabel = 'Not set',
}: {
  value: string | null;
  absentLabel?: string;
}) {
  return (
    <div className="cp-detail-value-group">
      {value ? (
        <span className="cp-detail-value">{value}</span>
      ) : (
        <span className="cp-detail-value cp-detail-value--absent">{absentLabel}</span>
      )}
    </div>
  );
}

/**
 * A field that reads as prose and edits in place -- or just reads, when there
 * is no token to save with.
 *
 * The read-only rendering is passed in rather than derived, so the same markup
 * serves both paths and an editable page cannot quietly start displaying its
 * data differently from a read-only one.
 */
function FieldSlot<T>({
  label,
  path,
  focus = null,
  wrapperClass,
  labelClass,
  editing,
  value,
  toChanges,
  validate,
  display,
  edit,
  editLabel = 'Edit',
}: {
  label: string;
  /** The dotted path, when this field is something an analysis can require. */
  path?: string;
  focus?: CareerFieldFocus | null;
  wrapperClass: string;
  labelClass: string;
  editing: CareerEditing | null;
  value: T;
  toChanges(draft: T): ProfileChanges;
  validate?(draft: T): string | null;
  display: ReactNode;
  edit(draft: T, setDraft: (next: T) => void): ReactNode;
  editLabel?: string;
}) {
  const node = useRef<HTMLDivElement>(null);
  // Only this field's own requests, and only as a changing number -- see
  // CareerFieldFocus on why the nonce rather than the path drives it.
  const nonce = path && focus?.path === path ? focus.nonce : null;

  // The slot moves the page and flags itself; the editor below opens itself.
  // Split that way because they are two different jobs on two different nodes,
  // and only this one owns an element to scroll to.
  useEffect(() => {
    if (nonce === null) return;
    const element = node.current;
    if (!element) return;
    revealField(element, () => element.querySelector<HTMLElement>('input, select, textarea'));
  }, [nonce]);

  if (!editing) {
    return (
      <div className={wrapperClass} ref={node} data-profile-field={path}>
        <span className={labelClass}>{label}</span>
        {display}
      </div>
    );
  }
  return (
    <div className={wrapperClass} ref={node} data-profile-field={path}>
      {/* EditableSection supplies the label here, so the static one above is
          not also rendered -- two headings for one field. */}
      <InlineEditableField
        title={label}
        value={value}
        toChanges={toChanges}
        validate={validate}
        persist={editing.persist}
        onSaved={editing.onSaved}
        openNonce={nonce}
        editLabel={editLabel}
      >
        {(draft, setDraft, isEditing) =>
          isEditing ? <div className="cp-field-edit">{edit(draft, setDraft)}</div> : display
        }
      </InlineEditableField>
    </div>
  );
}

/** A section shell: eyebrow, optional count, and a rule. */
function Section({
  title,
  count,
  children,
}: {
  title: string;
  count: number | null;
  children: React.ReactNode;
}) {
  return (
    <section className="cp-section">
      <div className="cp-section-head">
        <h3 className="cp-section-title">{title}</h3>
        {count !== null && count > 0 && <span className="cp-section-count">{count}</span>}
      </div>
      {children}
    </section>
  );
}

/**
 * A missing section, in one line.
 *
 * The old page spent a full card on three negative sentences. This is the whole
 * treatment: state the absence, and optionally say what filling it would do.
 *
 * Actions belong to the surrounding editable field shell. Keeping this
 * component presentational prevents an empty student-declared field from
 * quietly acquiring a route to an unrelated source of résumé evidence.
 */
function Absence({ line, help }: { line: string; help?: string }) {
  return (
    <div className="cp-absent">
      <p className="cp-absent-line">{line}</p>
      {help && <p className="cp-absent-help">{help}</p>}
    </div>
  );
}

/**
 * One role on the timeline.
 *
 * Employer is the marker and the anchor; role sits under it; duration and
 * location are secondary and appear ONLY when the record has them. Nothing is
 * substituted for a missing date -- an invented "Present" or "Dates unknown"
 * would be a claim about someone's employment history.
 */
function ExperienceRow({ entry }: { entry: ExperienceEntry }) {
  const meta = [entry.duration, entry.location].filter(Boolean);

  return (
    <li className="cp-tl-item">
      <span className="cp-tl-marker" aria-hidden="true" />
      <div className="cp-tl-body">
        <h4 className="cp-tl-org">{entry.employer ?? entry.role ?? 'Experience'}</h4>
        {entry.employer && entry.role && <p className="cp-tl-role">{entry.role}</p>}
        {meta.length > 0 && <p className="cp-tl-meta">{meta.join(' · ')}</p>}
        {entry.preview && <p className="cp-tl-desc">{entry.preview}</p>}
        {entry.skills.length > 0 && (
          <ul className="cp-chips cp-chips--tight">
            {entry.skills.map((skill) => (
              <li className="cp-chip cp-chip--quiet" key={skill}>
                {skill}
              </li>
            ))}
          </ul>
        )}
      </div>
    </li>
  );
}

/** One credential. Status is a real constrained column, not an inference. */
function CertificationRow({ entry }: { entry: CertificationEntry }) {
  const meta = [entry.issuer, entry.date].filter(Boolean);

  return (
    <li className="cp-cert">
      <h4 className="cp-cert-name">{entry.name ?? 'Untitled certification'}</h4>
      {meta.length > 0 && <p className="cp-cert-meta">{meta.join(' · ')}</p>}
      {entry.statusLabel && (
        <span
          className={`cp-cert-status${entry.status === 'completed' ? ' cp-cert-status--done' : ''}`}
        >
          {entry.statusLabel}
        </span>
      )}
    </li>
  );
}
