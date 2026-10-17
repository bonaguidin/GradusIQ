import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { useAuth } from '../auth/useAuth';
import { sendChat, type ChatMessage } from '../api/chat';
import './ChatPanel.css';

const SUGGESTIONS = [
  'What are my biggest skill gaps for my target roles?',
  'Which courses should I prioritize next term?',
  'How ready am I for an internship right now?',
];

export function ChatPanel({ autoFocus = false }: { autoFocus?: boolean } = {}) {
  const { slug, profile, session, studentAccount } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const realName = studentAccount.profile?.intelligence_profile.identity.name;
  const firstName = (profile?.student?.name ?? realName)?.split(' ')[0] ?? 'there';
  const canSend = Boolean(slug || session?.access_token);

  useEffect(() => {
    if (!autoFocus) return;
    inputRef.current?.focus({ preventScroll: true });
    inputRef.current?.scrollIntoView({ block: 'center' });
  }, [autoFocus]);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  }, [messages, sending]);

  async function submit(text: string) {
    const trimmed = text.trim();
    if (!trimmed || sending || !canSend) return;
    setError(null);
    const priorHistory = messages;
    setMessages((m) => [...m, { role: 'user', content: trimmed }]);
    setInput('');
    setSending(true);
    try {
      const reply = await sendChat(
        { slug, accessToken: session?.access_token ?? null },
        trimmed,
        priorHistory,
      );
      setMessages((m) => [...m, { role: 'assistant', content: reply }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong. Try again.');
    } finally {
      setSending(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void submit(input);
  }

  return (
    <section className="chat-panel" aria-label="Ask GradusIQ">
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
      </div>

      <div className="chat-messages" ref={listRef} aria-live="polite">
        {messages.length === 0 && (
          <div className="chat-empty">
            <p className="chat-empty-lead">
              Hi {firstName} — ask me anything about your record, gaps, or next steps.
            </p>
            <div className="chat-suggestions">
              {SUGGESTIONS.map((s) => (
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
            <div className="chat-msg-body">{m.content}</div>
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

      <form className="chat-input-row chat-composer" onSubmit={onSubmit}>
        {/* Stays enabled while a reply is pending so focus never drops after Enter;
            submit() ignores sends until the reply lands. */}
        <input
          ref={inputRef}
          className="chat-input"
          type="text"
          name="chat-message"
          value={input}
          onChange={(e) => setInput(e.target.value)}
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
