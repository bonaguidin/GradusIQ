import type { CareerBlock } from '../types/student';

interface CareerSummaryRowProps {
  career: CareerBlock;
  isEditing: boolean;
  onChange(updates: Partial<CareerBlock>): void;
}

export function CareerSummaryRow({ career, isEditing, onChange }: CareerSummaryRowProps) {
  if (!isEditing) {
    return (
      <div className="summary-row-view">
        <div className="summary-field">
          <span className="summary-label">Career Goals</span>
          <span className="summary-value">{career.career_goals || '—'}</span>
        </div>
        <div className="summary-field">
          <span className="summary-label">Geographic Preference</span>
          <span className="summary-value">{career.geographic_preference || '—'}</span>
        </div>
        <div className="summary-field">
          <span className="summary-label">AI Anxiety Level</span>
          <span className="summary-value">{career.ai_anxiety_level || '—'}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="summary-row-edit">
      <div className="form-group">
        <label htmlFor="career-goals" className="form-label">
          Career Goals
        </label>
        <textarea
          id="career-goals"
          name="career-goals"
          className="form-textarea"
          value={career.career_goals}
          onChange={(e) => onChange({ career_goals: e.target.value })}
          rows={3}
          autoComplete="off"
        />
      </div>
      <div className="form-group">
        <label htmlFor="geo-pref" className="form-label">
          Geographic Preference
        </label>
        <input
          id="geo-pref"
          name="geo-pref"
          type="text"
          className="form-input"
          value={career.geographic_preference}
          onChange={(e) => onChange({ geographic_preference: e.target.value })}
          autoComplete="off"
        />
      </div>
      <div className="form-group">
        <label htmlFor="ai-anxiety" className="form-label">
          AI Anxiety Level
        </label>
        <textarea
          id="ai-anxiety"
          name="ai-anxiety"
          className="form-textarea"
          value={career.ai_anxiety_level}
          onChange={(e) => onChange({ ai_anxiety_level: e.target.value })}
          rows={2}
          autoComplete="off"
        />
      </div>
    </div>
  );
}
