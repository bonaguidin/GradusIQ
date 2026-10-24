import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { saveMemory } from '../api/memory';
import { useAuth } from '../auth/useAuth';
import { useChat, useChatPage } from '../chat/ChatContext';
import { useChatAction } from '../chat/useChatAction';
import { CHAT_ACTIONS, usableActions } from '../lib/chatActions.mjs';
import { chatSuggestions } from '../lib/chatPage.mjs';
import { ChatMarkdown } from './ChatMarkdown';
import './ChatPanel.css';

interface ChatPanelProps {
  autoFocus?: boolean;
  /**
   * 'inline' is Overview's card. 'docked' is the side panel every other
   * signed-in page opens from the launcher (AssistantDock); it fills its
   * container and has a close button. Both show the same conversation.
   */
  variant?: 'inline' | 'docked';
  onClose?(): void;
}

export function ChatPanel({ autoFocus = false, variant = 'inline', onClose }: ChatPanelProps = {}) {
  const { profile, slug, session, studentAccount } = useAuth();
  // Memory notes belong to a real account; demo personas have nowhere to keep them.
  const memoryToken = slug ? null : session?.access_token ?? null;
  const runAction = useChatAction();
  const { messages, sending, error, canSend, send, reset, setRememberState } = useChat();
  const page = useChatPage();
  const suggestions = chatSuggestions(page);
  const [input, setInput] = useState('');
  // Shown when Enter is pressed with text while a reply is still pending.
  const [pendingNotice, setPendingNotice] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const realName = studentAccount.profile?.intelligence_profile.identity.name;
  const firstName = (profile?.student?.name ?? realName)?.split(' ')[0] ?? 'there';

  useEffect(() => {
    if (!autoFocus) return;
    inputRef.current?.focus({ preventScroll: true });
    // The docked panel is fixed to the viewport; scrolling it into view would
    // only move the page behind it.
    if (variant === 'inline') inputRef.current?.scrollIntoView({ block: 'center' });
  }, [autoFocus, variant]);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  }, [messages, sending]);

  async function submit(text: string) {
    const trimmed = text.trim();
    if (!trimmed || sending || !canSend) return;
    setPendingNotice(false);
    setInput('');
    await send(trimmed, page);
  }

  function startNewChat() {
    reset();
    setPendingNotice(false);
    inputRef.current?.focus();
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void submit(input);
  }

  return (
    <section className={`chat-panel chat-panel--${variant}`} aria-label="Ask GradusIQ">
      <div className="chat-header">
        <span className="chat-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z" />
          </svg>
        </span>
        <div className="chat-heading">
          <span className="chat-title">Ask <span translate="no">GradusIQ</span></span>
          <span className="chat-sub">
            Chat about your academics &amp; career — grounded in your profile and analysis.
          </span>
        </div>
        <div className="chat-header-actions">
          {messages.length > 0 && (
            <button type="button" className="btn btn-ghost btn-sm chat-new" onClick={startNewChat}>
              New chat
            </button>
          )}
          {onClose && (
            <button type="button" className="chat-close" onClick={onClose} aria-label="Close chat">
              <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round">
                <path d="M4 4l8 8M12 4l-8 8" />
              </svg>
            </button>
          )}
        </div>
      </div>

      <div className="chat-messages" ref={listRef} aria-live="polite">
        {messages.length === 0 && (
          <div className="chat-empty">
            <p className="chat-empty-lead">
              Hi {firstName} — ask me anything about your record, gaps, or next steps.
            </p>
            <div className="chat-suggestions">
              {suggestions.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="chat-chip"
                  onClick={() => {
                    inputRef.current?.focus();
                    void submit(s);
                  }}
                  disabled={sending || !canSend}
                >
                  <span>{s}</span>
                  <svg className="chat-chip-arrow" aria-hidden="true" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M3 8h10M9 4l4 4-4 4" />
                  </svg>
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={`chat-msg chat-msg--${m.role}`}>
            <span className="chat-msg-role">{m.role === 'user' ? 'You' : <span translate="no">GradusIQ</span>}</span>
            <div className="chat-msg-body">
              {m.role === 'assistant' ? <ChatMarkdown text={m.content} /> : m.content}
            </div>
            {m.role === 'assistant' && m.remember && memoryToken && m.rememberState !== 'dismissed' && (
              <RememberOffer
                note={m.remember}
                saved={m.rememberState === 'saved'}
                onSave={async () => {
                  await saveMemory(memoryToken, m.remember ?? '');
                  setRememberState(i, 'saved');
                }}
                onDismiss={() => setRememberState(i, 'dismissed')}
                // The side panel would cover the list's Forget buttons.
                onManage={() => runAction('career-profile', { closeChat: true, scrollTo: '.memory-notes' })}
              />
            )}
            {m.role === 'assistant' && (
              <ChatActions ids={usableActions(m.actions, { demo: Boolean(slug) })} onRun={runAction} />
            )}
          </div>
        ))}

        {sending && (
          <div className="chat-msg chat-msg--assistant">
            <span className="chat-msg-role" translate="no">GradusIQ</span>
            <div className="chat-msg-body chat-typing" aria-label="Thinking">
              <span />
              <span />
              <span />
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="chat-error" role="alert">
          {error}
        </div>
      )}
      {pendingNotice && sending && (
        <div className="chat-notice" role="status">
          Still answering your last message. Press Enter again once the reply arrives.
        </div>
      )}

      <form className="chat-input-row chat-composer" onSubmit={onSubmit}>
        {/* Stays enabled while a reply is pending so focus never drops after Enter;
            submit() ignores sends until the reply lands. */}
        <input
          ref={inputRef}
          className="chat-input"
          type="text"
          name="chat-message"
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            setPendingNotice(false);
          }}
          // The send button is disabled while a reply is pending, which also
          // stops Enter from submitting the form, so say why nothing happened.
          onKeyDown={(e) => {
            if (e.key === 'Enter' && sending && input.trim()) {
              e.preventDefault();
              setPendingNotice(true);
            }
          }}
          placeholder="Ask about your grades, gaps, roles…"
          disabled={!canSend}
          aria-label="Message GradusIQ"
          autoComplete="off"
        />
        <button
          type="submit"
          className="btn btn-primary btn-sm chat-send"
          disabled={sending || !input.trim() || !canSend}
        >
          <span>{sending ? '…' : 'Send'}</span>
          <svg className="chat-send-arrow" aria-hidden="true" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M8 13V3M4 7l4-4 4 4" />
          </svg>
        </button>
      </form>
    </section>
  );
}

/** The buttons under one assistant reply (lib/chatActions.mjs). */
function ChatActions({ ids, onRun }: { ids: string[]; onRun(id: string): void }) {
  if (ids.length === 0) return null;
  return (
    <div className="chat-actions">
      {ids.map((id) => (
        <button key={id} type="button" className="btn btn-secondary btn-sm chat-action" onClick={() => onRun(id)}>
          <span>{CHAT_ACTIONS[id].label}</span>
          <svg className="chat-action-arrow" aria-hidden="true" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 8h10M9 4l4 4-4 4" />
          </svg>
        </button>
      ))}
    </div>
  );
}

/**
 * The assistant offering to remember something the student said. Nothing is
 * saved until they press Remember (see ai/chat_memory.py).
 */
function RememberOffer({
  note,
  saved,
  onSave,
  onDismiss,
  onManage,
}: {
  note: string;
  saved: boolean;
  onSave(): Promise<void>;
  onDismiss(): void;
  onManage(): void;
}) {
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  if (saved) {
    return (
      <div className="chat-remember chat-remember--saved" role="status">
        <span>Saved to memory: <q>{note}</q></span>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onManage}>
          Manage
        </button>
      </div>
    );
  }

  return (
    <div className="chat-remember">
      <p className="chat-remember-ask">
        Remember this for future chats? <q>{note}</q>
      </p>
      <div className="chat-remember-buttons">
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          disabled={saving}
          onClick={async () => {
            setSaving(true);
            setFailure(null);
            try {
              await onSave();
            } catch (e) {
              setFailure(e instanceof Error ? e.message : 'Could not save that note.');
            } finally {
              setSaving(false);
            }
          }}
        >
          {saving ? 'Saving…' : 'Remember'}
        </button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onDismiss} disabled={saving}>
          No thanks
        </button>
      </div>
      {failure && <p className="chat-remember-error" role="alert">{failure}</p>}
    </div>
  );
}
