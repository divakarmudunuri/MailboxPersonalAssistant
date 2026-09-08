import { useEffect, useRef, useState } from "react";

const WELCOME =
  "Tell me how you want your inbox handled, for example “ignore GitHub notifications” or “anything from my landlord needs my review”. I will update your learned preferences.";

// Long-term memory: a chat that edits the learned preferences, beside a description of everything remembered.
export default function MemoryView() {
  const [memory, setMemory] = useState(null);
  const [error, setError] = useState("");
  const [messages, setMessages] = useState([{ role: "assistant", text: WELCOME }]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);

  function load() {
    fetch("/api/memory")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`API returned ${r.status}`))))
      .then((d) => { setMemory(d); setError(""); })
      .catch((e) => setError(`Could not reach the API: ${e.message}`));
  }

  useEffect(load, []);
  useEffect(() => { endRef.current?.scrollIntoView({ block: "nearest" }); }, [messages]);

  async function send(event) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    setMessages((m) => [...m, { role: "user", text }]);
    setDraft("");
    setBusy(true);
    try {
      const r = await fetch("/api/memory/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      if (!r.ok) throw new Error(`API returned ${r.status}`);
      const d = await r.json();
      setMessages((m) => [...m, { role: "assistant", text: d.reply }]);
      setMemory((mem) => mem && { ...mem, learned_preferences: d.learned_preferences });
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", text: `Sorry, that did not go through: ${e.message}`, error: true }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {error && <div className="error">{error}</div>}
      <div className="panes memory">
        <section className="detail chat">
          <h3>Teach the assistant</h3>
          <ol className="transcript">
            {messages.map((m, i) => (
              <li key={i} className={`bubble ${m.role}${m.error ? " error-text" : ""}`}>{m.text}</li>
            ))}
            {busy && <li className="bubble assistant muted">Updating…</li>}
            <li ref={endRef} />
          </ol>
          <form className="composer" onSubmit={send}>
            <input value={draft} placeholder="Describe a preference…" onChange={(e) => setDraft(e.target.value)} disabled={busy} aria-label="Message" />
            <button className="primary" type="submit" disabled={busy || !draft.trim()}>Send</button>
          </form>
        </section>

        <section className="detail prose">
          {!memory && <p className="empty">Loading memory…</p>}
          {memory && (
            <>
              <div className="brief-head">
                <p className="meta">What the assistant knows. Base rules live in the code; learned rules come from this chat and win when the two conflict. Every triaged email records which rule decided it.</p>
                <button onClick={load}>Refresh</button>
              </div>

              <h3 className="prose-heading">Learned preferences</h3>
              {memory.learned_preferences.trim()
                ? <pre className="body prose-text">{memory.learned_preferences}</pre>
                : <p className="empty">Nothing learned yet. Use the chat to add preferences.</p>}

              <h3 className="prose-heading">Senders</h3>
              {memory.senders.length === 0 && <p className="empty">No senders remembered yet.</p>}
              <ul className="prose-list">
                {memory.senders.map((s) => (
                  <li key={s.sender}>
                    Mail from <code>{s.sender}</code> was last marked <span className={`chip chip-${s.category}`}>{s.category}</span>
                    {s.count > 1 ? ` after ${s.count} emails` : ""}: {s.reason}
                  </li>
                ))}
              </ul>

              <h3 className="prose-heading">Base rules</h3>
              <ul className="prose-list">
                {memory.base_rules.map((r) => (
                  <li key={r.name}><code>{r.name}</code> {r.text} <span className="chip">{r.outcome}</span></li>
                ))}
              </ul>
            </>
          )}
        </section>
      </div>
    </>
  );
}
