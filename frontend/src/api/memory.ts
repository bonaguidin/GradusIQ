// Assistant memory notes (GradusIQ_career/ai/chat_memory.py): facts the
// student chose to have the assistant remember. Same fetch style as
// api/canvasCalendar.ts.

export const MEMORY_URL = '/api/v2/student/me/memory';

export interface MemoryNote {
  id: string;
  note: string;
  created_at?: string;
}

export interface MemoryList {
  /** False until the notes table exists; the app then hides the feature. */
  available: boolean;
  notes: MemoryNote[];
  maxNotes: number;
}

const auth = (token: string) => ({ Accept: 'application/json', Authorization: `Bearer ${token}` });

async function detail(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body?.detail === 'string') return body.detail;
  } catch {
    /* keep the fallback */
  }
  return fallback;
}

function isNote(value: unknown): value is MemoryNote {
  const v = value as MemoryNote;
  return !!v && typeof v.id === 'string' && typeof v.note === 'string';
}

export async function fetchMemory(token: string): Promise<MemoryList> {
  const response = await fetch(MEMORY_URL, { headers: auth(token) });
  if (!response.ok) throw new Error(await detail(response, 'Could not load your saved notes.'));
  const body = (await response.json()) as { available?: unknown; notes?: unknown; max_notes?: unknown };
  return {
    available: body.available === true,
    notes: Array.isArray(body.notes) ? body.notes.filter(isNote) : [],
    maxNotes: typeof body.max_notes === 'number' ? body.max_notes : 20,
  };
}

export async function saveMemory(token: string, note: string): Promise<void> {
  const response = await fetch(MEMORY_URL, {
    method: 'POST',
    headers: { ...auth(token), 'Content-Type': 'application/json' },
    body: JSON.stringify({ note }),
  });
  if (!response.ok) throw new Error(await detail(response, 'Could not save that note.'));
}

export async function deleteMemory(token: string, id: string): Promise<void> {
  const response = await fetch(`${MEMORY_URL}/${encodeURIComponent(id)}`, {
    method: 'DELETE',
    headers: auth(token),
  });
  if (!response.ok) throw new Error(await detail(response, 'Could not delete that note.'));
}
