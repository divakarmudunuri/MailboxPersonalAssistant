import { useEffect, useRef, useState } from "react";

const REASONS = ["promotions", "newsletter", "social", "spam", "subscription", "marketing", "notification", "miscellaneous"];

const WELCOME =
  "Tell me how you want your inbox handled, for example “ignore GitHub notifications” or “anything from my landlord needs my review”. I will update your learned preferences.";

// Long-term memory on the left, the chat that edits it on the right, and the pre-triage ignore list across the bottom.
export default function MemoryView() {
  const [memory, setMemory] = useState(null);
  const [error, setError] = useState("");
  const [messages, setMessages] = useState([{ role: "assistant", text: WELCOME }]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [ignore, setIgnore] = useState([]);
  const [newSender, setNewSender] = useState("");
  const [newReason, setNewReason] = useState("promotions");
  const endRef = useRef(null);

  function loadIgnore() {
    fetch("/api/ignore-list").then((r) => (r.ok ? r.json() : [])).then(setIgnore);
  }

  async function addIgnored(event) {
    event.preventDefault();
    const sender = newSender.trim();
    if (!sender) return;
    const r = await fetch("/api/ignore-list", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sender, ignore_reason_label: newReason }),
    });
    if (r.ok) { setIgnore(await r.json()); setNewSender(""); }
  }

  async function removeIgnored(sender) {
    const r = await fetch(`/api/ignore-list/${encodeURIComponent(sender)}`, { method: "DELETE" });
    if (r.ok) setIgnore(await r.json());
  }

  function load() {
    fetch("/api/memory")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`API returned ${r.status}`))))
      .then((d) => { setMemory(d); setError(""); })
      .catch((e) => setError(`Could not reach the API: ${e.message}`));
  }

  useEffect(load, []);
  useEffect(loadIgnore, []);
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

  const needle = newSender.trim().toLowerCase(); // typing a sender also highlights it in the cloud below
  const total = ignore.reduce((n, e) => n + e.senders.length, 0);

  return (
    <>
      {error && <div className="error">{error}</div>}
      <div className="panes memory">
        <section className="detail prose">
          <h3 className="prose-heading">Long-term memory</h3>
          {!memory && <p className="empty">Loading memory…</p>}
          {memory && (
            <>
              <div className="brief-head">
                <p className="meta">What the assistant knows. Base rules live in the code; learned rules come from the chat and win when the two conflict. Every triaged email records which rule decided it.</p>
                <button onClick={load}>Refresh</button>
              </div>

              <h3 className="prose-heading">Learned preferences</h3>
              {memory.learned_preferences.trim()
                ? <pre className="body prose-text">{memory.learned_preferences}</pre>
                : <p className="empty">Nothing learned yet. Use the chat to add preferences.</p>}

              <h3 className="prose-heading">Base rules</h3>
              <ul className="prose-list">
                {memory.base_rules.map((r) => (
                  <li key={r.name}><code>{r.name}</code> {r.text} <span className="chip">{r.outcome}</span></li>
                ))}
              </ul>
            </>
          )}
        </section>

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
      </div>

      <section className="detail ignore-panel">
        <div className="brief-head">
          <div>
            <h3 className="prose-heading">Pre-triage ignore list <span className="muted">{total}</span></h3>
            <p className="meta">Mail from these senders is marked ignore before any model call. Ignored senders are filed here instead of in memory, by reason. Type a sender to find it, or add it with a reason.</p>
          </div>
          <form className="composer" onSubmit={addIgnored}>
            <input value={newSender} placeholder="sender@example.com" onChange={(e) => setNewSender(e.target.value)} aria-label="Sender to ignore" />
            <select value={newReason} onChange={(e) => setNewReason(e.target.value)} aria-label="Ignore reason">
              {REASONS.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
            <button type="submit" disabled={!newSender.trim()}>Add</button>
          </form>
        </div>
        {ignore.length === 0 && <p className="empty">No senders on the list yet.</p>}
        <div className="cloud-groups">
          {ignore.map((entry) => (
            <div key={entry.ignore_reason_label} className="cloud-group">
              <h4><span className="chip chip-ignore">{entry.ignore_reason_label}</span> <span className="muted">{entry.senders.length}</span></h4>
              <div className="cloud">
                {entry.senders.map((s) => (
                  <span key={s} className={`tag${needle && !s.includes(needle) ? " dim" : ""}`}>
                    {s}
                    <button type="button" className="ghost small" onClick={() => removeIgnored(s)} title={`Remove ${s} from the list`} aria-label={`Remove ${s}`}>×</button>
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
