// Chat client — posts to the same-origin /api proxy, which injects the backend
// secret and forwards to FastAPI's POST /api/students/{slug}/chat. Mirrors the
// fetch style of api/analysis.ts, but sends a JSON body (message + history,
// plus the page the student has open -- see lib/chatPage.mjs).

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  /** Action button ids on an assistant reply (lib/chatActions.mjs). */
  actions?: string[];
}

export interface ChatReply {
  reply: string;
  actions: string[];
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
      history: history.map(({ role, content }) => ({ role, content })),
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

  const data = (await response.json()) as { reply?: string; actions?: unknown };
  const actions = Array.isArray(data.actions)
    ? data.actions.filter((a): a is string => typeof a === 'string')
    : [];
  return { reply: data.reply ?? '', actions };
}
