import { useState } from "react";
import GraphView from "./views/GraphView.jsx";
import HomeView from "./views/HomeView.jsx";
import MemoryView from "./views/MemoryView.jsx";
import TracesView from "./views/TracesView.jsx";
import TriageView from "./views/TriageView.jsx";

const TABS = [
  ["home", "Home"],
  ["triage", "Triage"],
  ["traces", "Traces"],
  ["memory", "Memory"],
  ["graph", "Graph"],
];

export default function App() {
  const [tab, setTab] = useState("home");

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
      {/* Triage stays mounted so its refresh timer and selection survive tab switches. */}
      <div hidden={tab !== "triage"}>
        <TriageView />
      </div>
      {tab === "traces" && <TracesView />}
      {tab === "memory" && <MemoryView />}
      {tab === "graph" && <GraphView />}
    </div>
  );
}
