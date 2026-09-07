import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import type { SyllabusProfileSummary } from '../api/syllabusGradeProfiles';
import { buildGradeCardModel, hoveredCenter } from '../lib/gradeCardRing.mjs';

// One square course card for the grade-calculator list. The ring is segmented
// by category weight and filled by score, in a single colour keyed to the
// letter grade (gradeCardRing.mjs builds the whole view-model; this file only
// renders it). The card is one tap target that opens the course; the Remove
// button is the only nested control. Segment hover is desktop-only progressive
// enhancement -- gated on `pointer: fine`, never on viewport width, and never
// wired on touch.

function useFinePointer(): boolean {
  const [fine, setFine] = useState(false);
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const mq = window.matchMedia('(pointer: fine)');
    const sync = () => setFine(mq.matches);
    sync();
    mq.addEventListener('change', sync);
    return () => mq.removeEventListener('change', sync);
  }, []);
  return fine;
}

interface GradeCardProps {
  profile: SyllabusProfileSummary;
  onOpen: () => void;
  onRemove: () => void;
  removing: boolean;
}

export function GradeCard({ profile, onOpen, onRemove, removing }: GradeCardProps) {
  const model = buildGradeCardModel(profile);
  const finePointer = useFinePointer();
  const [hovered, setHovered] = useState<number | null>(null);

  // A hover highlight is meaningless once the pointer stops being fine (e.g. a
  // hybrid device switching to touch) -- drop any stuck one.
  useEffect(() => {
    if (!finePointer) setHovered(null);
  }, [finePointer]);

  // The full breakdown lives in model.ariaLabel. For a ring card it rides on
  // the <svg role="img">; for setup / categoryless (no svg) it goes on the
  // button. Either way the visible title is redundant to AT -- hide it so the
  // card announces once, not "…breakdown… PHYS 207 Fall 2026".
  // The title row is always rendered, even when there's no title: its height
  // is reserved in CSS so a card is exactly the same height with or without
  // one (no placeholder text, no layout shift).
  const courseTitle = (
    <span className="grade-card-title" aria-hidden="true">
      <strong>{model.courseLabel}</strong>
      <small className="grade-card-title-name">{profile.course_title ?? ''}</small>
      {model.term ? <small>{model.term}</small> : null}
    </span>
  );

  let body: ReactNode;
  let dataGrade: string | undefined;

  if (model.kind === 'setup') {
    body = (
      <span className="grade-card-face grade-card-face--setup" aria-hidden="true">
        <span className="grade-card-setup-mark">+</span>
        <span className="grade-card-setup-text">Finish setup</span>
      </span>
    );
  } else if (model.kind === 'categoryless') {
    // Points-based syllabus: no weighted categories to segment a ring by. One
    // full-circle arc filled to the overall percentage, same grade-colour
    // keying, letter + percentage in the centre. No segments, no hover.
    dataGrade = model.colorKey ?? undefined;
    body = (
      <span className="grade-card-face">
        <svg className="grade-card-ring" viewBox="0 0 100 100" role="img" aria-label={model.ariaLabel}>
          <path className="grade-card-track" d={model.trackPath} aria-hidden="true" />
          {model.fillPath ? <path className="grade-card-fill" d={model.fillPath} aria-hidden="true" /> : null}
        </svg>
        <span className="grade-card-center" aria-hidden="true">
          <span className="grade-card-center-primary">{model.centerPrimary}</span>
          {model.centerSecondary ? (
            <span className="grade-card-center-secondary">{model.centerSecondary}</span>
          ) : null}
        </span>
      </span>
    );
  } else {
    dataGrade = model.colorKey ?? undefined;
    const activeSeg = hovered != null ? model.segments[hovered] ?? null : null;
    const center = activeSeg ? hoveredCenter(activeSeg) : null;
    body = (
      <span className="grade-card-face">
        <svg className="grade-card-ring" viewBox="0 0 100 100" role="img" aria-label={model.ariaLabel}>
          {model.segments.map((seg, i) => (
            <g
              key={seg.name}
              className="grade-card-seg"
              data-shortfall={seg.isShortfall ? '' : undefined}
              data-dim={hovered != null && hovered !== i ? '' : undefined}
              aria-hidden="true"
            >
              <path
                className={seg.isShortfall ? 'grade-card-track grade-card-track--shortfall' : 'grade-card-track'}
                d={seg.trackPath}
              />
              {seg.fillPath ? <path className="grade-card-fill" d={seg.fillPath} /> : null}
              {finePointer && !seg.isShortfall ? (
                <path
                  className="grade-card-hit"
                  d={seg.trackPath}
                  onMouseEnter={() => setHovered(i)}
                  onMouseLeave={() => setHovered((cur) => (cur === i ? null : cur))}
                />
              ) : null}
            </g>
          ))}
        </svg>
        <span className="grade-card-center" aria-hidden="true">
          <span className="grade-card-center-primary">{center ? center.primary : model.centerPrimary}</span>
          {center ? (
            <span className="grade-card-center-secondary">{center.secondary}</span>
          ) : model.centerSecondary ? (
            <span className="grade-card-center-secondary">{model.centerSecondary}</span>
          ) : null}
        </span>
      </span>
    );
  }

  return (
    <div className="grade-card-wrap">
      <button
        type="button"
        className="grade-card"
        data-kind={model.kind}
        data-grade={dataGrade}
        aria-label={model.kind === 'ring' ? undefined : model.ariaLabel}
        onClick={onOpen}
        onMouseLeave={() => setHovered(null)}
      >
        {body}
        {courseTitle}
      </button>
      <button
        type="button"
        className="btn btn-ghost btn-sm grade-card-remove"
        onClick={onRemove}
        disabled={removing}
        aria-label={`Remove grade calculator for ${model.courseLabel}`}
      >
        {removing ? 'Removing…' : 'Remove'}
      </button>
    </div>
  );
}
