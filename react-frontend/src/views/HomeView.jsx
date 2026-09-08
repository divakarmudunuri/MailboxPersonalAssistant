import { useEffect, useState } from "react";
import Prose from "../components/Prose.jsx";

const MAIL_DAYS = 14;
const REFRESH_MS = 30000;

// "Sam Lee <sam@example.com>" -> "Sam Lee"
function sender(from) {
  const match = from.match(/^\s*"?([^"<]+?)"?\s*</);
  return (match ? match[1] : from).trim();
}

function age(iso) {
  const minutes = Math.round((Date.now() - new Date(iso)) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  return hours < 24 ? `${hours} h ago` : `${Math.round(hours / 24)} d ago`;
}

// The start-of-day briefing: the last one is cached on the server; Build reads the inbox again.
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
      setError(`Could not build the briefing: ${e.message}`);
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
          <h2>Inbox briefing</h2>
          <p className="meta">
            {data?.generated_at
              ? `Built ${age(data.generated_at)} from ${counts.threads ?? 0} threads` + (data.rounds ? ` · ${data.rounds} rounds of reading` : "")
              : `A start-of-day briefing over the last ${MAIL_DAYS} days of mail.`}
          </p>
        </div>
        <button className="primary" onClick={build} disabled={busy}>
          {busy ? "Reading…" : briefing ? "Rebuild" : "Build briefing"}
        </button>
      </div>

      {error && <div className="error">{error}</div>}
      {!briefing && !busy && !error && (
        <p className="empty">No briefing yet. Building one reads your mail and costs a few model calls. It has no tool that could send or change anything.</p>
      )}
      {busy && !briefing && <p className="empty">Reading your inbox…</p>}

      {briefing && (
        <>
          <Prose text={briefing} />
          <div className="stats">
            <span><strong>{counts.threads ?? 0}</strong> threads, last {MAIL_DAYS} days</span>
            <span><strong>{counts.drafts ?? 0}</strong> replies already drafted</span>
            <span><strong>{data.tool_calls ?? 0}</strong> tool calls</span>
          </div>
        </>
      )}
    </section>

    <div className="home-side">
      <section className="detail panel">
        <h3>Waiting on you</h3>
        <p className="big">{home ? home.waiting.total : "…"}</p>
        <p className="meta">Triage items waiting on you: to read, drafts to review, and mail triage could not decide.</p>
        <ul className="prose-list compact">
          {home?.waiting.items.slice(0, 6).map((e) => (
            <li key={e.id}><span className={`chip chip-${e.category}`}>{e.category}</span> {sender(e.sender)}: {e.subject || "(no subject)"}</li>
          ))}
        </ul>
      </section>

      <section className="detail panel">
        <h3>Actions taken by the agent</h3>
        <p className="big">{home ? home.actions.total : "…"}</p>
        <p className="meta">Reminders created, invitations answered, drafts saved.</p>
        <ul className="prose-list compact">
          {home?.actions.items.slice(0, 6).map((e) => (
            <li key={e.id}><strong>{sender(e.sender)}</strong>, {e.subject || "(no subject)"}<br /><span className="muted">{e.action}</span></li>
          ))}
        </ul>
      </section>
    </div>
    </div>
  );
}
