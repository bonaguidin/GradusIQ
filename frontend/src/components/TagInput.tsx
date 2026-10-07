import { useState, useRef } from 'react';

interface TagInputProps {
  label: string;
  value: string[];
  onChange(v: string[]): void;
  placeholder?: string;
  disabled?: boolean;
}

export function TagInput({ label, value, onChange, placeholder = 'Add…', disabled = false }: TagInputProps) {
  const [inputVal, setInputVal] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  function addTag(raw: string) {
    const tag = raw.trim();
    if (!tag) return;
    if (value.includes(tag)) {
      setInputVal('');
      return;
    }
    onChange([...value, tag]);
    setInputVal('');
  }

  function removeTag(tag: string) {
    onChange(value.filter((t) => t !== tag));
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      addTag(inputVal);
    } else if (e.key === 'Backspace' && inputVal === '' && value.length > 0) {
      // Remove last tag on backspace when input is empty
      onChange(value.slice(0, -1));
    }
  }

  function handleBlur() {
    if (inputVal.trim()) {
      addTag(inputVal);
    }
  }

  const inputId = `tag-input-${label.replace(/\s+/g, '-').toLowerCase()}`;

  return (
    <div className="tag-input-field">
      <label htmlFor={inputId} className="form-label">
        {label}
      </label>
      <div
        className={`tag-input-container ${disabled ? 'tag-input-disabled' : ''}`}
        onClick={() => !disabled && inputRef.current?.focus()}
      >
        {value.map((tag) => (
          <span key={tag} className="tag-chip">
            {tag}
            {!disabled && (
              <button
                type="button"
                className="tag-remove"
                onClick={(e) => {
                  e.stopPropagation();
                  removeTag(tag);
                }}
                aria-label={`Remove ${tag}`}
              >
                ×
              </button>
            )}
          </span>
        ))}
        {!disabled && (
          <input
            ref={inputRef}
            id={inputId}
            name={inputId}
            type="text"
            className="tag-text-input"
            value={inputVal}
            onChange={(e) => setInputVal(e.target.value)}
            onKeyDown={handleKeyDown}
            onBlur={handleBlur}
            placeholder={value.length === 0 ? placeholder : ''}
            aria-label={label}
            autoComplete="off"
          />
        )}
      </div>
    </div>
  );
}
