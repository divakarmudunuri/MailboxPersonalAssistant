import { useEffect, useState } from "react";
import GraphView from "./views/GraphView.jsx";
import HomeView from "./views/HomeView.jsx";
import MemoryView from "./views/MemoryView.jsx";
import TracesView from "./views/TracesView.jsx";
import InboxView from "./views/InboxView.jsx";

const TABS = [
  ["home", "Home"],
  ["inbox", "Inbox"],
  ["traces", "Traces"],
  ["memory", "Memory"],
  ["graph", "Graph"],
];

export default function App() {
  const [tab, setTab] = useState("home");
  const [open, setOpen] = useState(null); // {id, reply} from the URL hash: #inbox/<id> or #inbox/<id>/reply

  // Links on the Home tab point at #inbox/<id> (show the email) or #inbox/<id>/reply (and open its reply form).
  useEffect(() => {
    const follow = () => {
      const match = window.location.hash.match(/^#inbox\/([A-Za-z0-9]+)(\/reply)?$/);
      if (!match) return;
      setTab("inbox");
      setOpen({ id: match[1], reply: Boolean(match[2]), at: Date.now() });
      // Clear the hash once it is handled, so the same link works again and the address bar stays clean.
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
    };
    follow();
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, []);

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>Mail Assistant</h1>
          <p className="sub">Gmail triage with a local or cloud model</p>
        </div>
      </header>

      <nav className="tabs">
        {TABS.map(([key, label]) => (
          <button key={key} className={key === tab ? "tab active" : "tab"} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </nav>

      {tab === "home" && <HomeView />}
      {/* Inbox stays mounted so its refresh timer and selection survive tab switches. */}
      <div hidden={tab !== "inbox"}>
        <InboxView open={open} />
      </div>
      {tab === "traces" && <TracesView />}
      {tab === "memory" && <MemoryView />}
      {tab === "graph" && <GraphView />}
    </div>
  );
}
