import { useEffect, useState } from "react";
import Prose from "../components/Prose.jsx";

const MAIL_DAYS = 30;
const REFRESH_MS = 30000;

// "Sam Lee <sam@example.com>" -> "Sam Lee"
function sender(from) {
  const match = from.match(/^\s*"?([^"<]+?)"?\s*</);
  return (match ? match[1] : from).trim();
}

// "save_draft: draft saved, Message-ID <...>; create_reminder: ..." -> what a person would say happened.
const ACTIONS = [["save_draft", "Draft reply saved"], ["create_reminder", "Reminder created"], ["respond_to_invite", "Invitation answered"]];
function describe(action) {
  const parts = String(action || "").split("; ").map((part) => {
    const hit = ACTIONS.find(([tool]) => part.startsWith(tool));
    return hit ? hit[1] : part.replace(/^no action:\s*/i, "No action: ");
  });
  return [...new Set(parts)].join(", ");
}

function age(iso) {
  const minutes = Math.round((Date.now() - new Date(iso)) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  return hours < 24 ? `${hours} h ago` : `${Math.round(hours / 24)} d ago`;
}

// The Quick Overview: the last one is cached on the server; Build reads the inbox again.
export default function HomeView() {
  const [data, setData] = useState(null);
  const [home, setHome] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/report").then((r) => (r.ok ? r.json() : Promise.reject(new Error(`API returned ${r.status}`))))
      .then(setData).catch((e) => setError(`Could not reach the API: ${e.message}`));
  }, []);

  // The side panels follow the store, which changes as the watcher works, so they refresh on a timer.
  useEffect(() => {
    const load = () => fetch("/api/home").then((r) => (r.ok ? r.json() : null)).then((d) => d && setHome(d));
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, []);

  async function build() {
    setBusy(true);
    setError("");
    try {
      const r = await fetch("/api/report/refresh", { method: "POST" });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `API returned ${r.status}`);
      setData(await r.json());
    } catch (e) {
      setError(`Could not build the overview: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  const briefing = data?.briefing;
  const counts = data?.counts || {};

  return (
    <div className="home">
    <section className="detail">
      <div className="brief-head">
        <div>
          <h2>Quick Overview</h2>
          <p className="meta">
            {data?.generated_at
              ? `Built ${age(data.generated_at)} from ${counts.candidates ?? 0} threads, one model call`
              : `Unread and needs-review counts, what is waiting on you, deadlines, and the first thing to do, over the last ${MAIL_DAYS} days of mail.`}
          </p>
        </div>
        <button className="primary" onClick={build} disabled={busy}>
          {busy ? "Reading…" : briefing ? "Rebuild" : "Build overview"}
        </button>
      </div>

      {error && <div className="error">{error}</div>}
      {!briefing && !busy && !error && (
        <p className="empty">No overview yet. Building one reads your stored mail, the Sent folder, and the calendar, and costs one model call. Nothing on this path can send or change anything.</p>
      )}
      {busy && !briefing && <p className="empty">Reading your inbox…</p>}

      {briefing && (
        <>
          <Prose text={briefing} />
          <div className="stats">
            <span><strong>{counts.unread ?? 0}</strong> unread</span>
            <span><strong>{counts.needs_review ?? 0}</strong> need review, last {MAIL_DAYS} days</span>
            <span><strong>{counts.events_today ?? 0}</strong> events today and tomorrow</span>
            <span><strong>{counts.pending_invites ?? 0}</strong> invitations unanswered</span>
          </div>
        </>
      )}
    </section>

    <div className="home-side">
      <section className="detail panel">
        <h3>Actions taken by the agent</h3>
        <p className="big">{home ? home.actions.total : "…"}</p>
        <p className="meta">Reminders created, invitations answered, drafts saved.</p>
        <ul className="prose-list compact">
          {home?.actions.items.slice(0, 6).map((e) => (
            <li key={e.id}>
              <strong>{sender(e.sender)}</strong>, {e.subject || "(no subject)"}<br />
              <span className="muted">{describe(e.action)}</span>
              {" · "}
              {e.action.startsWith("save_draft")
                ? <a className="prose-link" href={`#inbox/${e.id}/reply`}>Review draft and send</a>
                : <a className="prose-link" href={`#inbox/${e.id}`}>Open in Inbox</a>}
            </li>
          ))}
        </ul>
      </section>
    </div>
    </div>
  );
}
