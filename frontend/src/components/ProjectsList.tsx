import { TagInput } from './TagInput';
import type { Project } from '../types/student';

interface ProjectsListProps {
  projects: Project[];
  isEditing: boolean;
  onChange(projects: Project[]): void;
}

function emptyProject(): Project {
  return {
    name: '',
    timeframe: '',
    description: '',
    tools: [],
  };
}

export function ProjectsList({ projects, isEditing, onChange }: ProjectsListProps) {
  if (!isEditing) {
    if (!projects || projects.length === 0) {
      return <p className="empty-state">No projects added yet.</p>;
    }
    return (
      <div className="projects-list">
        {projects.map((proj, idx) => (
          <div key={idx} className="project-card">
            <div className="proj-header">
              <strong className="proj-name">{proj.name}</strong>
              {proj.timeframe && (
                <span className="proj-timeframe">{proj.timeframe}</span>
              )}
            </div>
            {proj.description && <p className="proj-description">{proj.description}</p>}
            {proj.tools && proj.tools.length > 0 && (
              <div className="tag-chips-view proj-tools">
                {proj.tools.map((t) => (
                  <span key={t} className="tag-chip tag-chip-view">
                    {t}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    );
  }

  function updateAt(idx: number, updates: Partial<Project>) {
    const next = projects.map((proj, i) => (i === idx ? { ...proj, ...updates } : proj));
    onChange(next);
  }

  function removeAt(idx: number) {
    onChange(projects.filter((_, i) => i !== idx));
  }

  function addNew() {
    onChange([...projects, emptyProject()]);
  }

  return (
    <div className="projects-edit">
      {projects.map((proj, idx) => (
        <div key={idx} className="proj-edit-card">
          <div className="exp-edit-header">
            <span className="exp-edit-index">Project {idx + 1}</span>
            <button
              type="button"
              className="btn btn-danger-ghost btn-sm"
              onClick={() => removeAt(idx)}
              aria-label={`Remove project ${idx + 1}`}
            >
              Remove
            </button>
          </div>
          <div className="form-row">
            <div className="form-group">
              <label htmlFor={`proj-name-${idx}`} className="form-label">
                Name
              </label>
              <input
                id={`proj-name-${idx}`}
                name={`proj-name-${idx}`}
                type="text"
                className="form-input"
                value={proj.name}
                onChange={(e) => updateAt(idx, { name: e.target.value })}
                autoComplete="off"
              />
            </div>
            <div className="form-group">
              <label htmlFor={`proj-timeframe-${idx}`} className="form-label">
                Timeframe
              </label>
              <input
                id={`proj-timeframe-${idx}`}
                name={`proj-timeframe-${idx}`}
                type="text"
                className="form-input"
                value={proj.timeframe}
                onChange={(e) => updateAt(idx, { timeframe: e.target.value })}
                autoComplete="off"
              />
            </div>
          </div>
          <div className="form-group">
            <label htmlFor={`proj-desc-${idx}`} className="form-label">
              Description
            </label>
            <textarea
              id={`proj-desc-${idx}`}
              name={`proj-desc-${idx}`}
              className="form-textarea"
              value={proj.description}
              onChange={(e) => updateAt(idx, { description: e.target.value })}
              rows={3}
              autoComplete="off"
            />
          </div>
          <TagInput
            label="Tools"
            value={proj.tools ?? []}
            onChange={(tools) => updateAt(idx, { tools })}
            placeholder="Add a tool and press Enter…"
          />
        </div>
      ))}
      <button
        type="button"
        className="btn btn-ghost btn-add"
        onClick={addNew}
      >
        + Add Project
      </button>
    </div>
  );
}
