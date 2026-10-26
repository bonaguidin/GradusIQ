// Chat client — posts to the same-origin /api proxy, which injects the backend
// secret and forwards to FastAPI's POST /api/students/{slug}/chat. Mirrors the
// fetch style of api/analysis.ts, but sends a JSON body (message + history,
// plus the page the student has open -- see lib/chatPage.mjs).

/** A change the assistant offered (backend ai/chat_changes.py); see chat/runProposal.ts. */
export interface ChatProposal {
  id: string;
  kind: string;
  /** The card's text, e.g. "Add CS 3353 (Data Structures) to your Spring 2027 plan". */
  summary: string;
  payload: Record<string, unknown>;
}

export interface ProposalState {
  state: 'done' | 'dismissed';
  /** What happened, shown on the card once done. */
  message?: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  /** Action button ids on an assistant reply (lib/chatActions.mjs). */
  actions?: string[];
  /** A fact the assistant offered to remember (api/memory.ts). */
  remember?: string;
  /** What the student did with that offer. */
  rememberState?: 'saved' | 'dismissed';
  /** What the assistant looked up for this reply, e.g. "your degree plan". */
  lookups?: string[];
  /** Changes offered on this reply, and what the student did with each. */
  proposals?: ChatProposal[];
  proposalStates?: Record<string, ProposalState>;
}

export interface ChatReply {
  reply: string;
  actions: string[];
  remember: string | null;
  lookups: string[];
  proposals: ChatProposal[];
}

function parseProposals(value: unknown): ChatProposal[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (p): p is ChatProposal =>
      !!p && typeof p === 'object' && typeof p.id === 'string' && typeof p.kind === 'string' &&
      typeof p.summary === 'string' && !!p.payload && typeof p.payload === 'object',
  );
}

/**
 * What a past message says when sent back as history. The backend takes
 * role and content only, so a change the student confirmed or turned down
 * is noted in the text; otherwise the assistant would offer it again.
 */
export function historyContent(message: ChatMessage): string {
  const notes = (message.proposals ?? []).flatMap((p) => {
    const state = message.proposalStates?.[p.id]?.state;
    if (state === 'done') return [`(The student confirmed: ${p.summary}.)`];
    if (state === 'dismissed') return [`(The student declined: ${p.summary}.)`];
    return [];
  });
  return notes.length ? `${message.content}\n\n${notes.join('\n')}` : message.content;
}

export async function sendChat(
  identity: { slug: string | null; accessToken: string | null },
  message: string,
  history: ChatMessage[],
  page: string | null = null,
): Promise<ChatReply> {
  const path = identity.slug
    ? `/api/students/${encodeURIComponent(identity.slug)}/chat`
    : '/api/v2/student/me/chat';
  if (!identity.slug && !identity.accessToken) {
    throw new Error('Authenticated chat requires a session.');
  }
  const response = await fetch(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(identity.slug ? {} : { Authorization: `Bearer ${identity.accessToken}` }),
    },
    // The backend takes role and content only; buttons stay in the browser.
    body: JSON.stringify({
      message,
      history: history.map((m) => ({ role: m.role, content: historyContent(m) })),
      ...(page ? { page } : {}),
    }),
  });

  if (!response.ok) {
    let detail = `Chat request failed (${response.status}).`;
    try {
      const data = await response.json();
      if (data && typeof data.detail === 'string') detail = data.detail;
    } catch {
      /* keep the default message */
    }
    throw new Error(detail);
  }

  const data = (await response.json()) as {
    reply?: string;
    actions?: unknown;
    remember?: unknown;
    lookups?: unknown;
    proposals?: unknown;
  };
  const strings = (value: unknown) =>
    Array.isArray(value) ? value.filter((a): a is string => typeof a === 'string') : [];
  const remember = typeof data.remember === 'string' && data.remember.trim() ? data.remember.trim() : null;
  return { reply: data.reply ?? '', actions: strings(data.actions), remember, lookups: strings(data.lookups),
    proposals: parseProposals(data.proposals),
  };
}
