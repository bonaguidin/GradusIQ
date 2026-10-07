import type { Certification } from '../types/student';

interface CertificationsListProps {
  certifications: Certification[];
  isEditing: boolean;
  onChange(certifications: Certification[]): void;
}

function emptyCertification(): Certification {
  return {
    name: '',
    issuer: '',
    status: '',
    date: '',
  };
}

export function CertificationsList({ certifications, isEditing, onChange }: CertificationsListProps) {
  if (!isEditing) {
    if (!certifications || certifications.length === 0) {
      return <p className="empty-state">No certifications yet.</p>;
    }
    return (
      <div className="cert-list">
        {certifications.map((cert, idx) => (
          <div key={idx} className="cert-card">
            <strong className="cert-name">{cert.name}</strong>
            <span className="cert-issuer">{cert.issuer}</span>
            <span className="cert-status">{cert.status}</span>
            {cert.date && <span className="cert-date">{cert.date}</span>}
          </div>
        ))}
      </div>
    );
  }

  function updateAt(idx: number, updates: Partial<Certification>) {
    const next = certifications.map((c, i) => (i === idx ? { ...c, ...updates } : c));
    onChange(next);
  }

  function removeAt(idx: number) {
    onChange(certifications.filter((_, i) => i !== idx));
  }

  function addNew() {
    onChange([...certifications, emptyCertification()]);
  }

  return (
    <div className="cert-edit">
      {certifications.length === 0 && (
        <p className="empty-state">No certifications yet. Add one below.</p>
      )}
      {certifications.map((cert, idx) => (
        <div key={idx} className="cert-edit-card">
          <div className="exp-edit-header">
            <span className="exp-edit-index">Certification {idx + 1}</span>
            <button
              type="button"
              className="btn btn-danger-ghost btn-sm"
              onClick={() => removeAt(idx)}
              aria-label={`Remove certification ${idx + 1}`}
            >
              Remove
            </button>
          </div>
          <div className="form-row">
            <div className="form-group">
              <label htmlFor={`cert-name-${idx}`} className="form-label">
                Name
              </label>
              <input
                id={`cert-name-${idx}`}
                name={`cert-name-${idx}`}
                type="text"
                className="form-input"
                value={cert.name}
                onChange={(e) => updateAt(idx, { name: e.target.value })}
                autoComplete="off"
              />
            </div>
            <div className="form-group">
              <label htmlFor={`cert-issuer-${idx}`} className="form-label">
                Issuer
              </label>
              <input
                id={`cert-issuer-${idx}`}
                name={`cert-issuer-${idx}`}
                type="text"
                className="form-input"
                value={cert.issuer}
                onChange={(e) => updateAt(idx, { issuer: e.target.value })}
                autoComplete="organization"
              />
            </div>
          </div>
          <div className="form-row">
            <div className="form-group">
              <label htmlFor={`cert-status-${idx}`} className="form-label">
                Status
              </label>
              <input
                id={`cert-status-${idx}`}
                name={`cert-status-${idx}`}
                type="text"
                className="form-input"
                value={cert.status}
                onChange={(e) => updateAt(idx, { status: e.target.value })}
                autoComplete="off"
              />
            </div>
            <div className="form-group">
              <label htmlFor={`cert-date-${idx}`} className="form-label">
                Date (optional)
              </label>
              <input
                id={`cert-date-${idx}`}
                name={`cert-date-${idx}`}
                type="text"
                className="form-input"
                value={cert.date ?? ''}
                onChange={(e) => updateAt(idx, { date: e.target.value })}
                autoComplete="off"
                // No inputMode="numeric" -- values like "Spring 2024" or
                // "Expected 2025" are valid here, and a numeric keypad would
                // make those harder to type, not easier.
                placeholder="e.g. May 2024"
              />
            </div>
          </div>
        </div>
      ))}
      <button
        type="button"
        className="btn btn-ghost btn-add"
        onClick={addNew}
      >
        + Add Certification
      </button>
    </div>
  );
}
