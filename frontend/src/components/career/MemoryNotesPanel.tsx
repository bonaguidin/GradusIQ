import { useEffect, useState } from 'react';
import { deleteMemory, fetchMemory } from '../../api/memory';
import type { MemoryNote } from '../../api/memory';

/**
 * "What GradusIQ remembers": the notes the student saved from the assistant
 * chat (ai/chat_memory.py), each deletable. Hidden entirely until the notes
 * table exists, and on a failed load, since there is nothing to manage then.
 */
export function MemoryNotesPanel({ accessToken }: { accessToken: string }) {
  const [notes, setNotes] = useState<MemoryNote[] | null>(null);
  const [maxNotes, setMaxNotes] = useState(20);
  const [removing, setRemoving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetchMemory(accessToken)
      .then((result) => {
        if (!live) return;
        setNotes(result.available ? result.notes : null);
        setMaxNotes(result.maxNotes);
      })
      .catch(() => {
        if (live) setNotes(null);
      });
    return () => {
      live = false;
    };
  }, [accessToken]);

  if (notes === null) return null;

  async function forget(id: string) {
    setRemoving(id);
    setError(null);
    try {
      await deleteMemory(accessToken, id);
      setNotes((current) => (current ?? []).filter((n) => n.id !== id));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not delete that note.');
    } finally {
      setRemoving(null);
    }
  }

  return (
    <section className="cp-section memory-notes" aria-labelledby="memory-notes-title">
      <div className="cp-section-head">
        <h3 className="cp-section-title" id="memory-notes-title">What GradusIQ remembers</h3>
        {notes.length > 0 && <span className="cp-section-count">{notes.length} of {maxNotes}</span>}
      </div>
      <p className="memory-notes-intro">
        Things you asked the assistant to remember. They are used in every chat, and only you can see them here.
      </p>
      {notes.length === 0 ? (
        <p className="memory-notes-empty">
          Nothing yet. When you tell the assistant about a goal or preference, it will offer to remember it.
        </p>
      ) : (
        <ul className="memory-notes-list">
          {notes.map((n) => (
            <li key={n.id} className="memory-note">
              <span className="memory-note-text">{n.note}</span>
              <button
                type="button"
                className="btn btn-danger-ghost btn-sm"
                onClick={() => void forget(n.id)}
                disabled={removing !== null}
                aria-label={`Forget: ${n.note}`}
              >
                {removing === n.id ? 'Forgetting…' : 'Forget'}
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && <p className="memory-notes-error" role="alert">{error}</p>}
    </section>
  );
}
