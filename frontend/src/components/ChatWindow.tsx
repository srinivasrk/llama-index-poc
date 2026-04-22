"use client";

import { useState } from "react";

import { chat } from "@/lib/api";
import type { ChatResponse } from "@/lib/api";

type Message = {
  role: "user" | "assistant";
  text: string;
  citations?: ChatResponse["citations"];
};

export function ChatWindow() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const canSend = question.trim().length > 0 && !busy;

  async function onSend() {
    if (!canSend) return;
    const q = question.trim();
    const userHistory = messages
      .filter((m) => m.role === "user")
      .map((m) => m.text)
      .slice(-6);
    setQuestion("");
    setError("");
    setMessages((prev) => [...prev, { role: "user", text: q }]);
    setBusy(true);
    try {
      const res = await chat(q, userHistory);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: res.answer, citations: res.citations },
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSend(); }
  }

  return (
    <section className="card">
      <h2 className="card-title">Chat</h2>
      <p className="card-subtitle">
        The assistant answers only from retrieved knowledge base chunks — it refuses out-of-scope questions.
      </p>

      {/* Message list */}
      <div className="soft-box" style={styles.chatBox}>
        {messages.length === 0 ? (
          <p style={styles.placeholder}>Ask a question after ingesting documents.</p>
        ) : (
          messages.map((msg, i) => (
            <div key={i} style={msg.role === "user" ? styles.userMsg : styles.assistantMsg}>
              <div style={{
                ...styles.roleLabel,
                color: msg.role === "user" ? "var(--md-primary)" : "var(--md-secondary)",
              }}>
                {msg.role === "user" ? "You" : "Assistant"}
              </div>
              <p style={styles.msgText}>{msg.text}</p>
              {msg.citations && msg.citations.length > 0 && (
                <div style={styles.citations}>
                  {msg.citations.map((c, ci) => (
                    <span key={ci} className="chip chip-primary" title={`Score: ${c.score.toFixed(3)}`}>
                      {c.source}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))
        )}
        {busy && (
          <div style={styles.assistantMsg}>
            <div style={{ ...styles.roleLabel, color: "var(--md-secondary)" }}>Assistant</div>
            <p style={{ ...styles.msgText, color: "var(--md-on-surface-variant)" }}>Thinking…</p>
          </div>
        )}
      </div>

      {error && (
        <div style={styles.error} className="mono">{error}</div>
      )}

      {/* Input row */}
      <div style={styles.inputRow}>
        <input
          className="input"
          placeholder="Ask something about your knowledge base…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={busy}
        />
        <button
          className="button button-primary"
          style={styles.sendBtn}
          onClick={onSend}
          disabled={!canSend}
        >
          {busy ? "Sending…" : "Send"}
        </button>
      </div>
    </section>
  );
}

const styles: Record<string, React.CSSProperties> = {
  chatBox: {
    padding: 12,
    minHeight: 240,
    maxHeight: 400,
    overflowY: "auto",
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  placeholder: {
    color: "var(--md-on-surface-variant)",
    padding: "8px 4px",
    fontSize: 13,
  },
  userMsg: {
    padding: "10px 14px",
    borderRadius: "18px 18px 4px 18px",
    background: "var(--md-primary-container)",
    color: "var(--md-on-primary-container)",
    alignSelf: "flex-end",
    maxWidth: "88%",
  },
  assistantMsg: {
    padding: "10px 14px",
    borderRadius: "18px 18px 18px 4px",
    background: "var(--md-surface-container-high)",
    color: "var(--md-on-surface)",
    alignSelf: "flex-start",
    maxWidth: "92%",
  },
  roleLabel: {
    fontSize: 11,
    fontWeight: 600,
    letterSpacing: "0.04em",
    textTransform: "uppercase",
    marginBottom: 5,
  },
  msgText: {
    whiteSpace: "pre-wrap",
    lineHeight: 1.55,
    fontSize: 14,
  },
  citations: {
    marginTop: 8,
    display: "flex",
    flexWrap: "wrap",
    gap: 6,
  },
  inputRow: {
    display: "flex",
    gap: 10,
    alignItems: "center",
    marginTop: 14,
  },
  sendBtn: {
    minWidth: 88,
    flexShrink: 0,
  },
  error: {
    marginTop: 10,
    padding: "10px 14px",
    borderRadius: 12,
    background: "var(--md-error-container)",
    color: "var(--md-on-error-container)",
    border: "1px solid rgba(255,180,171,0.2)",
    lineHeight: 1.5,
  },
};
