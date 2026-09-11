import { useEffect, useState } from "react";

const PAGE_SIZE = 20;
const REFRESH_MS = 30000;
const STEPS = ["inbox_manager", "memory", "triage", "pre_triage", "manual_user_input", "inbox_report", "memory_chat"];

const fmtTime = (iso) => new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "medium" });

// "Sam Lee <sam@example.com>" -> "Sam Lee"
function sender(from) {
  const match = from.match(/^\s*"?([^"<]+?)"?\s*</);
  return (match ? match[1] : from).trim();
}

// Every graph step, newest first, with the category and rule it produced; filtered to one step (inbox manager by default).
export default function TracesView() {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [step, setStep] = useState("inbox_manager");
  const [page, setPage] = useState(1);
  const [data, setData] = useState({ items: [], total: 0 });
  const [error, setError] = useState("");

  function load() {
    const params = new URLSearchParams({ page, page_size: PAGE_SIZE });
    if (query) params.set("q", query);
    if (step) params.set("step", step);
    fetch(`/api/traces?${params}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`API returned ${r.status}`))))
      .then((d) => { setData(d); setError(""); })
      .catch((e) => setError(`Could not reach the API: ${e.message}`));
  }

  useEffect(() => {
    const t = setTimeout(() => { setQuery(search.trim()); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [query, step, page]);

  const pages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));

  return (
    <>
      {error && <div className="error">{error}</div>}

      <div className="pager">
        <select value={step} onChange={(e) => { setStep(e.target.value); setPage(1); }} aria-label="Step filter">
          {STEPS.map((s) => <option key={s} value={s}>{s}</option>)}
          <option value="">all steps</option>
        </select>
        <input
          type="search"
          value={search}
          placeholder="Search step, action, sender, subject, category, rule, or reason…"
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search traces"
        />
        <span className="count">{data.total} {data.total === 1 ? "entry" : "entries"}</span>
        <span className="spacer" />
        <button onClick={load}>Refresh</button>
        <button disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
        <span className="count">{page} / {pages}</span>
        <button disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button>
      </div>

      <div className="tablewrap">
        <table>
          <thead>
            <tr><th>When</th><th>Step</th><th>Action</th><th>From</th><th>Subject</th><th>Category</th><th>Rule</th><th>Reason</th><th>ms</th></tr>
          </thead>
          <tbody>
            {data.items.length === 0 && (
              <tr><td colSpan={9} className="muted-cell">{query ? `No trace entries match “${query}”.` : step ? `No ${step} entries yet.` : "No traces yet. Entries appear as emails are processed."}</td></tr>
            )}
            {data.items.map((t, i) => (
              <tr key={`${t.email_id}-${t.step}-${t.at}-${i}`}>
                <td className="nowrap">{fmtTime(t.at)}</td>
                <td><span className={`chip chip-step-${t.step}`}>{t.step}</span></td>
                <td className="mono">{t.action_taken || "—"}</td>
                <td title={t.sender}>{t.sender ? sender(t.sender) : "—"}</td>
                <td title={t.subject}>{t.subject || "(no subject)"}</td>
                <td>{t.category ? <span className={`chip chip-${t.category}`}>{t.category}</span> : "—"}</td>
                <td className="mono">{t.rule || "—"}</td>
                <td className="reason-cell">{t.reason}</td>
                <td className="numeric">{t.duration_ms}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
