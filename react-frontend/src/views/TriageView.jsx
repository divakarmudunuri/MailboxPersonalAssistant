import { useEffect, useRef, useState } from "react";

const CATEGORIES = ["ignore", "notify", "agentrespond", "user_reply_complete", "agentdraftonly", "pending"];
const PAGE_SIZE = 20;
const REFRESH_MS = 30000;

// "Sam Lee <sam@example.com>" -> "Sam Lee"
function sender(from) {
  const match = from.match(/^\s*"?([^"<]+?)"?\s*</);
  return (match ? match[1] : from).trim();
}

const fmtDate = (iso) => new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });

export default function TriageView() {
  const [category, setCategory] = useState("notify"); // only notify is shown until the user picks another
  const [search, setSearch] = useState(""); // what is typed
  const [query, setQuery] = useState(""); // debounced value sent to the API
  const [page, setPage] = useState(1);
  const [data, setData] = useState({ items: [], total: 0 });
  const [selected, setSelected] = useState(null);
  const [form, setForm] = useState({ category: "", reason: "" });
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
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

  function select(email) {
    setSelected(email);
    setForm({ category: email.category, reason: email.reason });
    setSaved(false);
    // On narrow screens the detail sits below the list, so bring it into view.
    if (window.innerWidth <= 820) detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function filter(c) {
    setCategory(c);
    setPage(1);
  }

  async function save() {
    const r = await fetch(`/api/emails/${selected.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    if (!r.ok) { setError(`Save failed: API returned ${r.status}`); return; }
    const updated = await r.json();
    setSelected(updated);
    setData((d) => ({ ...d, items: d.items.map((e) => (e.id === updated.id ? updated : e)) }));
    setSaved(true);
  }

  return (
    <>
      {error && <div className="error">{error}</div>}

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
