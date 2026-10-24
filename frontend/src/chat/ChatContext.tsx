import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { chatPageKey } from '../lib/chatPage.mjs';
import { sendChat, type ChatMessage } from '../api/chat';

/**
 * One assistant conversation for the whole signed-in app.
 *
 * Overview's inline chat and the side panel on every other page read and
 * write this same store, so a conversation follows the student from page to
 * page, and a reply that is still on its way lands even if they navigate
 * while waiting.
 *
 * It is kept in sessionStorage, per signed-in identity: a refresh keeps the
 * conversation, a new tab or a new browser session starts fresh, and signing
 * out clears it. Nothing is stored on the server yet (that is Phase 4 of the
 * chat plan, which needs a migration and a retention decision first).
 */

export interface ChatStore {
  messages: ChatMessage[];
  sending: boolean;
  error: string | null;
  canSend: boolean;
  /** Sends one message; the caller has already trimmed and checked it. */
  send(text: string, page: string | null): Promise<void>;
  /** Starts a new, empty conversation. */
  reset(): void;
  /** Records what the student did with a "Remember this?" offer. */
  setRememberState(index: number, state: 'saved' | 'dismissed'): void;
  /** Whether the side panel is open. Lives here so it survives navigation. */
  panelOpen: boolean;
  setPanelOpen(open: boolean): void;
}

const STORAGE_PREFIX = 'gradusiq.chat.v1:';
// Enough for a long session; the backend only reads the last 12 turns anyway.
const MAX_STORED_MESSAGES = 40;

const ChatContext = createContext<ChatStore | null>(null);

// sessionStorage can throw (blocked storage, some private modes). The
// conversation is a convenience, so a failure just means it isn't kept.
function readStored(key: string | null): ChatMessage[] {
  if (!key) return [];
  try {
    const raw = window.sessionStorage.getItem(key);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (m): m is ChatMessage =>
          !!m && (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string',
      )
      .map((m) => ({
        role: m.role,
        content: m.content,
        ...(Array.isArray(m.actions) ? { actions: m.actions.filter((a) => typeof a === 'string') } : {}),
        ...(typeof m.remember === 'string' ? { remember: m.remember } : {}),
        ...(m.rememberState === 'saved' || m.rememberState === 'dismissed' ? { rememberState: m.rememberState } : {}),
      }));
  } catch {
    return [];
  }
}

function writeStored(key: string, messages: ChatMessage[]): void {
  try {
    if (messages.length === 0) window.sessionStorage.removeItem(key);
    else window.sessionStorage.setItem(key, JSON.stringify(messages.slice(-MAX_STORED_MESSAGES)));
  } catch {
    /* not kept; see readStored */
  }
}

function removeStored(key: string): void {
  try {
    window.sessionStorage.removeItem(key);
  } catch {
    /* see readStored */
  }
}

function useChatState(persist: boolean): ChatStore {
  const { slug, session } = useAuth();
  const accessToken = session?.access_token ?? null;
  const userId = session?.user?.id ?? null;
  // Demo personas are keyed by slug; real students by their auth user id.
  const identityKey = slug ? `${STORAGE_PREFIX}demo:${slug}` : userId ? `${STORAGE_PREFIX}${userId}` : null;
  const storageKey = persist ? identityKey : null;
  const canSend = Boolean(slug || accessToken);

  // Messages are held together with the identity they belong to, so the
  // write below can never save one student's conversation under another's key
  // in the render where the identity changes.
  const [conversation, setConversation] = useState(() => ({
    key: storageKey,
    messages: readStored(storageKey),
  }));
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);

  if (conversation.key !== storageKey) {
    // Identity changed (sign-out, another demo persona): show that identity's
    // conversation instead. Adjusting state during render is React's
    // documented pattern for state derived from a changed input.
    setConversation({ key: storageKey, messages: readStored(storageKey) });
    setError(null);
    setPanelOpen(false);
  }

  // Signing out leaves no conversation behind in the tab.
  const previousKey = useRef(storageKey);
  useEffect(() => {
    if (previousKey.current && !storageKey) removeStored(previousKey.current);
    previousKey.current = storageKey;
  }, [storageKey]);

  useEffect(() => {
    if (conversation.key) writeStored(conversation.key, conversation.messages);
  }, [conversation]);

  const messages = conversation.key === storageKey ? conversation.messages : [];
  const setMessages = useCallback(
    (update: (current: ChatMessage[]) => ChatMessage[]) =>
      setConversation((c) => ({ key: c.key, messages: update(c.messages) })),
    [],
  );

  // A reply belongs to the conversation it was asked in. "New chat" or a
  // change of identity while waiting bumps this, and the late reply is dropped.
  const generation = useRef(0);

  const send = useCallback(
    async (text: string, page: string | null) => {
      const asked = generation.current;
      const history = messages;
      setError(null);
      setMessages(() => [...history, { role: 'user', content: text }]);
      setSending(true);
      try {
        const { reply, actions, remember } = await sendChat({ slug, accessToken }, text, history, page);
        if (generation.current === asked) {
          setMessages((m) => [
            ...m,
            {
              role: 'assistant',
              content: reply,
              ...(actions.length ? { actions } : {}),
              ...(remember ? { remember } : {}),
            },
          ]);
        }
      } catch (e) {
        if (generation.current === asked) {
          setError(e instanceof Error ? e.message : 'Something went wrong. Try again.');
        }
      } finally {
        if (generation.current === asked) setSending(false);
      }
    },
    [messages, setMessages, slug, accessToken],
  );

  useEffect(() => {
    generation.current += 1;
    setSending(false);
  }, [storageKey]);

  const reset = useCallback(() => {
    generation.current += 1;
    setMessages(() => []);
    setSending(false);
    setError(null);
  }, [setMessages]);

  const setRememberState = useCallback(
    (index: number, state: 'saved' | 'dismissed') =>
      setMessages((current) =>
        current.map((m, i) => (i === index ? { ...m, rememberState: state } : m)),
      ),
    [setMessages],
  );

  return useMemo(
    () => ({ messages, sending, error, canSend, send, reset, setRememberState, panelOpen, setPanelOpen }),
    [messages, sending, error, canSend, send, reset, setRememberState, panelOpen],
  );
}

interface DashboardLocation {
  path: string;
  /** Query params every dashboard link keeps (the preview harness's fixture). */
  keepParams: readonly string[];
}

const NO_PARAMS: readonly string[] = [];
const DashboardPathContext = createContext<DashboardLocation>({ path: '/dashboard', keepParams: NO_PARAMS });

/**
 * `dashboardPath` and `keepParams` are only for the preview harness, which
 * serves the dashboard from its own .html path with fixture params.
 */
export function ChatProvider({
  children,
  dashboardPath = '/dashboard',
  keepParams = NO_PARAMS,
}: {
  children: ReactNode;
  dashboardPath?: string;
  keepParams?: readonly string[];
}) {
  const store = useChatState(true);
  const location = useMemo(() => ({ path: dashboardPath, keepParams }), [dashboardPath, keepParams]);
  return (
    <DashboardPathContext.Provider value={location}>
      <ChatContext.Provider value={store}>{children}</ChatContext.Provider>
    </DashboardPathContext.Provider>
  );
}

/** The open page's key (lib/chatPage.mjs), or null where the chat isn't offered. */
export function useChatPage(): string | null {
  const location = useLocation();
  const dashboard = useContext(DashboardPathContext);
  return chatPageKey(location.pathname, new URLSearchParams(location.search), dashboard.path);
}

/** Where the dashboard lives, for building action-button links. */
export function useDashboardLocation(): DashboardLocation {
  return useContext(DashboardPathContext);
}

/**
 * The shared conversation. Outside a ChatProvider (the preview harnesses that
 * render one page on its own) it falls back to a conversation local to the
 * calling component, which is how the chat behaved before the panel existed.
 */
export function useChat(): ChatStore {
  const shared = useContext(ChatContext);
  // Always called, so hook order never changes; it only persists when there
  // is no shared store to defer to.
  const local = useChatState(shared === null);
  return shared ?? local;
}
