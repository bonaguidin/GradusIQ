import { TagInput } from './TagInput';
import type { SkillsSelfReported } from '../types/student';

interface SkillsEditorProps {
  skills: SkillsSelfReported;
  isEditing: boolean;
  onChange(skills: SkillsSelfReported): void;
}

export function SkillsEditor({ skills, isEditing, onChange }: SkillsEditorProps) {
  if (!isEditing) {
    return (
      <div className="skills-view">
        <div className="skills-group">
          <span className="skills-group-label">Technical</span>
          <div className="tag-chips-view">
            {skills.technical && skills.technical.length > 0 ? (
              skills.technical.map((s) => (
                <span key={s} className="tag-chip tag-chip-view">
                  {s}
                </span>
              ))
            ) : (
              <span className="text-muted">None listed</span>
            )}
          </div>
        </div>
        <div className="skills-group">
          <span className="skills-group-label">Soft Skills</span>
          <div className="tag-chips-view">
            {skills.soft && skills.soft.length > 0 ? (
              skills.soft.map((s) => (
                <span key={s} className="tag-chip tag-chip-view">
                  {s}
                </span>
              ))
            ) : (
              <span className="text-muted">None listed</span>
            )}
          </div>
        </div>
        <div className="skills-group">
          <span className="skills-group-label">AI Exposure</span>
          <span className="summary-value">{skills.ai_exposure || '—'}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="skills-edit">
      <TagInput
        label="Technical Skills"
        value={skills.technical ?? []}
        onChange={(technical) => onChange({ ...skills, technical })}
        placeholder="Add a skill and press Enter…"
      />
      <TagInput
        label="Soft Skills"
        value={skills.soft ?? []}
        onChange={(soft) => onChange({ ...skills, soft })}
        placeholder="Add a skill and press Enter…"
      />
      <div className="form-group">
        <label htmlFor="ai-exposure" className="form-label">
          AI Exposure
        </label>
        <textarea
          id="ai-exposure"
          name="ai-exposure"
          className="form-textarea"
          value={skills.ai_exposure}
          onChange={(e) => onChange({ ...skills, ai_exposure: e.target.value })}
          rows={2}
          autoComplete="off"
        />
      </div>
    </div>
  );
}
