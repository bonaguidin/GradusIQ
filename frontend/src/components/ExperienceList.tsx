import { TagInput } from './TagInput';
import type { WorkExperience } from '../types/student';

interface ExperienceListProps {
  experiences: WorkExperience[];
  isEditing: boolean;
  onChange(experiences: WorkExperience[]): void;
}

function emptyExperience(): WorkExperience {
  return {
    employer: '',
    role: '',
    duration: '',
    location: '',
    description: '',
    skills_gained: [],
  };
}

export function ExperienceList({ experiences, isEditing, onChange }: ExperienceListProps) {
  if (!isEditing) {
    if (!experiences || experiences.length === 0) {
      return <p className="empty-state">No work experience added yet.</p>;
    }
    return (
      <div className="experience-list">
        {experiences.map((exp, idx) => (
          <div key={idx} className="experience-card">
            <div className="exp-header">
              <strong className="exp-employer">{exp.employer}</strong>
              <span className="exp-role">{exp.role}</span>
            </div>
            <div className="exp-meta">
              <span>{exp.duration}</span>
              {exp.location && <span> · {exp.location}</span>}
            </div>
            {exp.description && <p className="exp-description">{exp.description}</p>}
            {exp.skills_gained && exp.skills_gained.length > 0 && (
              <div className="tag-chips-view exp-skills">
                {exp.skills_gained.map((s) => (
                  <span key={s} className="tag-chip tag-chip-view">
                    {s}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    );
  }

  function updateAt(idx: number, updates: Partial<WorkExperience>) {
    const next = experiences.map((exp, i) => (i === idx ? { ...exp, ...updates } : exp));
    onChange(next);
  }

  function removeAt(idx: number) {
    onChange(experiences.filter((_, i) => i !== idx));
  }

  function addNew() {
    onChange([...experiences, emptyExperience()]);
  }

  return (
    <div className="experience-edit">
      {experiences.map((exp, idx) => (
        <div key={idx} className="exp-edit-card">
          <div className="exp-edit-header">
            <span className="exp-edit-index">Experience {idx + 1}</span>
            <button
              type="button"
              className="btn btn-danger-ghost btn-sm"
              onClick={() => removeAt(idx)}
              aria-label={`Remove experience ${idx + 1}`}
            >
              Remove
            </button>
          </div>
          <div className="form-row">
            <div className="form-group">
              <label htmlFor={`exp-employer-${idx}`} className="form-label">
                Employer
              </label>
              <input
                id={`exp-employer-${idx}`}
                name={`exp-employer-${idx}`}
                type="text"
                className="form-input"
                value={exp.employer}
                onChange={(e) => updateAt(idx, { employer: e.target.value })}
                autoComplete="organization"
              />
            </div>
            <div className="form-group">
              <label htmlFor={`exp-role-${idx}`} className="form-label">
                Role
              </label>
              <input
                id={`exp-role-${idx}`}
                name={`exp-role-${idx}`}
                type="text"
                className="form-input"
                value={exp.role}
                onChange={(e) => updateAt(idx, { role: e.target.value })}
                autoComplete="off"
              />
            </div>
          </div>
          <div className="form-row">
            <div className="form-group">
              <label htmlFor={`exp-duration-${idx}`} className="form-label">
                Duration
              </label>
              <input
                id={`exp-duration-${idx}`}
                name={`exp-duration-${idx}`}
                type="text"
                className="form-input"
                value={exp.duration}
                onChange={(e) => updateAt(idx, { duration: e.target.value })}
                autoComplete="off"
              />
            </div>
            <div className="form-group">
              <label htmlFor={`exp-location-${idx}`} className="form-label">
                Location
              </label>
              <input
                id={`exp-location-${idx}`}
                name={`exp-location-${idx}`}
                type="text"
                className="form-input"
                value={exp.location}
                onChange={(e) => updateAt(idx, { location: e.target.value })}
                autoComplete="off"
              />
            </div>
          </div>
          <div className="form-group">
            <label htmlFor={`exp-desc-${idx}`} className="form-label">
              Description
            </label>
            <textarea
              id={`exp-desc-${idx}`}
              name={`exp-desc-${idx}`}
              className="form-textarea"
              value={exp.description}
              onChange={(e) => updateAt(idx, { description: e.target.value })}
              rows={3}
              autoComplete="off"
            />
          </div>
          <TagInput
            label="Skills Gained"
            value={exp.skills_gained ?? []}
            onChange={(skills_gained) => updateAt(idx, { skills_gained })}
            placeholder="Add a skill and press Enter…"
          />
        </div>
      ))}
      <button
        type="button"
        className="btn btn-ghost btn-add"
        onClick={addNew}
      >
        + Add Experience
      </button>
    </div>
  );
}
