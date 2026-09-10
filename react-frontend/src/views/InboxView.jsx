import { useEffect, useRef, useState } from "react";

const CATEGORIES = ["ignore", "notify", "auto_schedule", "user_reply_complete", "auto_draft", "pending"];
const PAGE_SIZE = 20;
const REFRESH_MS = 30000;

// Addresses nobody reads: noreply@, no-reply@, donotreply@, do-not-reply@, do_not_reply@, and anything with
// "notification" in the address, such as notifications@github.com; Reply is hidden for these.
const noReply = (from) => /\b(no[-_]?reply|do[-_]?not[-_]?reply)\b|notification/i.test(from);

// "Sam Lee <sam@example.com>" -> "Sam Lee"
function sender(from) {
  const match = from.match(/^\s*"?([^"<]+?)"?\s*</);
  return (match ? match[1] : from).trim();
}

const fmtDate = (iso) => new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });

export default function InboxView({ open = null }) {
  const [category, setCategory] = useState("notify"); // only notify is shown until the user picks another
  const [search, setSearch] = useState(""); // what is typed
  const [query, setQuery] = useState(""); // debounced value sent to the API
  const [page, setPage] = useState(1);
  const [data, setData] = useState({ items: [], total: 0 });
  const [selected, setSelected] = useState(null);
  const [form, setForm] = useState({ category: "", reason: "" });
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [reply, setReply] = useState(null); // the draft being edited: {to, subject, body, draft_message_id}
  const [busy, setBusy] = useState(""); // "drafting" | "sending" | ""
  const [sent, setSent] = useState(false);
  const [notice, setNotice] = useState(""); // a confirmation shown above the list, so it survives a refresh
  const [ignoring, setIgnoring] = useState(false); // the Ignore button was pressed and a reason is being asked for
  const [ignoreReason, setIgnoreReason] = useState("");
  const detailRef = useRef(null);

  function load() {
    const params = new URLSearchParams({ page, page_size: PAGE_SIZE });
    if (category) params.set("category", category);
    if (query) params.set("q", query);
    fetch(`/api/emails?${params}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`API returned ${r.status}`))))
      .then((d) => { setData(d); setError(""); })
      .catch((e) => setError(`Could not reach the API: ${e.message}`));
  }

  // Debounce typing so the API is not hit on every keystroke.
  useEffect(() => {
    const t = setTimeout(() => { setQuery(search.trim()); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [search]);

  // Reload the list whenever the filter, search, or page changes, and every REFRESH_MS after that.
  useEffect(() => {
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [category, query, page]);

  const pages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));

  // An email named by the URL hash (a link on the Home tab) is fetched and shown, the list filter is switched to the
  // email's category so it appears in the list too, and its reply form is opened when the link asked for it.
  useEffect(() => {
    if (!open) return;
    fetch(`/api/emails/${open.id}`).then((r) => (r.ok ? r.json() : null)).then((e) => {
      if (!e) return;
      setSearch(""); setCategory(e.category); setPage(1);
      select(e);
      if (open.reply) startReply(e);
    });
  }, [open]);

  function select(email) {
    setSelected(email);
    setForm({ category: email.category, reason: email.reason });
    setSaved(false);
    setReply(null);
    setSent(false);
    setIgnoring(false);
    setIgnoreReason("");
    // On narrow screens the detail sits below the list, so bring it into view.
    if (window.innerWidth <= 820) detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // Changing the list filter also drops the selection, so the detail pane never shows an email from the old view;
  // an unsent reply draft is the one thing worth a confirm first.
  function filter(c) {
    if (reply !== null && !window.confirm("Changing the filter will discard the reply you are editing. Continue?")) return;
    setSelected(null); setReply(null); setIgnoring(false); setSent(false);
    setCategory(c);
    setPage(1);
  }

  // Replace the selected email everywhere it is shown.
  function replaceSelected(updated) {
    setSelected(updated);
    setData((d) => ({ ...d, items: d.items.map((e) => (e.id === updated.id ? updated : e)) }));
  }

  async function post(path, body) {
    const r = await fetch(`/api/emails/${selected.id}/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!r.ok) {
      const detail = await r.json().catch(() => ({}));
      throw new Error(detail.detail || `API returned ${r.status}`);
    }
    return r.json();
  }

  async function markRead() {
    try { replaceSelected(await post("read")); setError(""); } catch (e) { setError(`Mark as read failed: ${e.message}`); }
  }

  // "Sam Lee <sam@example.com>" -> "sam@example.com"
  const address = (from) => (from.match(/<([^>]+)>/) || [null, from])[1].trim();

  // Reply starts from the draft the inbox manager already wrote, if there is one; otherwise an empty reply.
  async function startReply(email = selected) {
    setError("");
    const r = await fetch(`/api/emails/${email.id}/draft`);
    if (r.ok) { setReply({ ...(await r.json()), fromManager: true }); return; }
    const subject = /^re:/i.test(email.subject) ? email.subject : `Re: ${email.subject}`;
    setReply({ to: address(email.sender), subject, body: "", draft_message_id: "", fromManager: false });
  }

  // Ask the inbox manager to write the draft now (it is stored, and saved in Gmail's Drafts too).
  async function draftWithManager() {
    setBusy("drafting");
    try { setReply({ ...(await post("draft")), fromManager: true }); setError(""); } catch (e) { setError(`Drafting failed: ${e.message}`); }
    setBusy("");
  }

  async function send() {
    setBusy("sending");
    try {
      const updated = await post("send", reply);
      replaceSelected(updated);
      setNotice(`Reply sent to ${reply.to}: “${reply.subject}”. The email is now marked as replied.`);
      setReply(null);
      setSent(true);
      setError("");
      refreshAfter(updated, false);
    } catch (e) { setError(`Send failed: ${e.message}`); }
    setBusy("");
  }

  // After a decision moves the email out of the current filter, refresh: the list reloads from the API and the detail
  // pane clears, so a stale selection does not linger. Ask first only when work is in progress (an unsent reply draft).
  function refreshAfter(updated, inProgress) {
    if (!category || updated.category === category) return;
    if (inProgress) {
      const ok = window.confirm(`Saved as ${updated.category}. Reloading the screen will discard the reply you are editing. Reload now?`);
      if (!ok) return;
    }
    setSelected(null); setReply(null); setIgnoring(false); load();
  }

  // Save a category and reason as the user's decision; the API runs the graph so it is stored, remembered, and traced.
  async function decide(body) {
    const r = await fetch(`/api/emails/${selected.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) { setError(`Save failed: API returned ${r.status}`); return false; }
    const updated = await r.json();
    replaceSelected(updated);
    setForm({ category: updated.category, reason: updated.reason });
    refreshAfter(updated, reply !== null);
    return true;
  }

  async function save() {
    if (await decide(form)) setSaved(true);
  }

  async function ignore() {
    if (await decide({ category: "ignore", reason: ignoreReason.trim() })) { setIgnoring(false); setIgnoreReason(""); }
  }

  return (
    <>
      {error && <div className="error">{error}</div>}
      {notice && (
        <div className="notice" role="status">
          <span>{notice}</span>
          <button className="ghost small" onClick={() => setNotice("")} aria-label="Dismiss">×</button>
        </div>
      )}

      <div className="pager">
        <input
          type="search"
          value={search}
          placeholder="Search sender, subject, or body…"
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search emails"
        />
        <select value={category} onChange={(e) => filter(e.target.value)} aria-label="Category filter">
          {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
          <option value="">all categories</option>
        </select>
        <span className="count">{data.total} {data.total === 1 ? "email" : "emails"} · refreshes every {REFRESH_MS / 1000} s</span>
        <span className="spacer" />
        <button onClick={load}>Refresh</button>
        <button disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
        <span className="count">{page} / {pages}</span>
        <button disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button>
      </div>

      <div className="panes">
        <ul className="list">
          {data.items.length === 0 && (
            <li className="empty">
              {query ? `No emails match “${query}”.` : category ? `No ${category} emails yet.` : "No emails yet."}
            </li>
          )}
          {data.items.map((e) => (
            <li key={e.id} className={e.id === selected?.id ? "row selected" : "row"} onClick={() => select(e)}>
              <div className="row-top">
                <span className="from" title={e.sender}>{sender(e.sender)}</span>
                <span className={`status status-${e.category}`}>{e.category}</span>
              </div>
              <div className="subject">{e.subject || "(no subject)"}</div>
              <div className="meta">{fmtDate(e.received_at)}{e.applied_rule ? ` · ${e.applied_rule}` : ""}</div>
            </li>
          ))}
        </ul>

        <section className="detail" ref={detailRef}>
          {!selected && <p className="empty">Select an email.</p>}
          {selected && (
            <>
              <h2>{selected.subject || "(no subject)"}</h2>
              <p className="meta">From {selected.sender} · {fmtDate(selected.received_at)}</p>
              {selected.category === "user_reply_complete" ? (
                <p className="hint">You already replied on this thread{selected.action ? ` (${selected.action})` : ""}.</p>
              ) : selected.category === "auto_schedule" ? (
                <p className="hint">Handled on the calendar by the inbox manager{selected.action ? ` (${selected.action})` : ""}.</p>
              ) : (
              <div className="buttons">
                <button onClick={markRead} disabled={!selected.label_ids.includes("UNREAD")}>
                  {selected.label_ids.includes("UNREAD") ? "Mark as read" : "Read"}
                </button>
                {noReply(selected.sender)
                  ? <p className="hint">Sent from a no-reply address.</p>
                  : <button className="primary" onClick={startReply} disabled={busy !== "" || reply !== null}>
                      {busy === "drafting" ? "Drafting…" : "Reply"}
                    </button>}
                <button onClick={() => { setIgnoring(true); setIgnoreReason(""); }} disabled={selected.category === "ignore" || ignoring}>
                  {selected.category === "ignore" ? "Ignored" : "Ignore"}
                </button>
                {sent && <p className="hint">Sent. The email is now marked as replied.</p>}
              </div>
              )}

              {ignoring && (
                <>
                  <h3>Ignore</h3>
                  <div className="fields">
                    <label>
                      <span>Why ignore this?</span>
                      <textarea rows={2} value={ignoreReason} placeholder="e.g. marketing newsletter, subscription notice, spam" autoFocus
                        onChange={(e) => setIgnoreReason(e.target.value)} />
                    </label>
                  </div>
                  <div className="buttons">
                    <button className="primary" onClick={ignore} disabled={!ignoreReason.trim()}>Save as ignored</button>
                    <button onClick={() => setIgnoring(false)}>Cancel</button>
                    <p className="hint">The reason is remembered for this sender; a reason about the sender puts them on the pre-triage ignore list.</p>
                  </div>
                </>
              )}

              {reply && (
                <>
                  <h3>Reply</h3>
                  <div className="fields">
                    <label><span>To</span><input value={reply.to} onChange={(e) => setReply({ ...reply, to: e.target.value })} /></label>
                    <label><span>Subject</span><input value={reply.subject} onChange={(e) => setReply({ ...reply, subject: e.target.value })} /></label>
                    <label><span>Message</span><textarea rows={10} value={reply.body} onChange={(e) => setReply({ ...reply, body: e.target.value })} /></label>
                  </div>
                  <div className="buttons">
                    <button className="primary" onClick={send} disabled={busy !== "" || !reply.to.trim() || !reply.body.trim()}>
                      {busy === "sending" ? "Sending…" : "Send"}
                    </button>
                    <button onClick={() => setReply(null)} disabled={busy !== ""}>Discard</button>
                    {!reply.fromManager && (
                      <button onClick={draftWithManager} disabled={busy !== ""}>{busy === "drafting" ? "Drafting…" : "Draft with the manager"}</button>
                    )}
                    <p className="hint">
                      {busy === "drafting" ? "The inbox manager is reading the thread and writing a draft."
                        : reply.fromManager ? "Drafted by the inbox manager and also saved in Gmail's Drafts; edit freely before sending."
                        : "No draft was prepared for this email; write your reply, or ask the manager for one."}
                    </p>
                  </div>
                </>
              )}

              <h3>Decision</h3>
              <span className={`chip chip-${selected.category}`}>{selected.category}</span>
              {selected.applied_rule && <span className="rule">rule <code>{selected.applied_rule}</code></span>}
              <p className="reason">{selected.reason || "No reason recorded."}</p>
              {selected.action && <p className="reason"><strong>Action:</strong> {selected.action}</p>}

              <h3>Email</h3>
              <pre className="body">{selected.body_text || selected.snippet}</pre>

              <h3>Change decision</h3>
              <div className="fields">
                <label>
                  <span>Category</span>
                  <select value={form.category} onChange={(e) => { setForm({ ...form, category: e.target.value }); setSaved(false); }}>
                    {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </label>
                <label>
                  <span>Reason</span>
                  <textarea rows={3} value={form.reason} onChange={(e) => { setForm({ ...form, reason: e.target.value }); setSaved(false); }} />
                </label>
              </div>
              <div className="buttons">
                <button className="primary" onClick={save}>Save</button>
                {saved && <p className="hint">Saved. This is now the remembered preference for the sender.</p>}
              </div>
            </>
          )}
        </section>
      </div>
    </>
  );
}
