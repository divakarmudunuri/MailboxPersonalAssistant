import { useEffect, useState } from "react";

const COL = 220; // horizontal distance between layers
const ROW = 54; // vertical distance between nodes in one layer
const NODE_W = 172;
const NODE_H = 34;
const PAD = 40;

const label = (id) => (id === "__start__" ? "start" : id === "__end__" ? "end" : id.replace(/^[a-z]+__/, ""));

// Layered layout: each node's column is its distance from start over forward edges; nodes in a column are stacked.
// Edges that point back to an earlier column are return edges (a tool handing control back to the model).
function layout(graph) {
  const out = {};
  for (const e of graph.edges) (out[e.source] = out[e.source] || []).push(e.target);
  const depth = { __start__: 0 };
  const queue = ["__start__"];
  while (queue.length) {
    const n = queue.shift();
    for (const t of out[n] || []) {
      if (depth[t] === undefined) { depth[t] = depth[n] + 1; queue.push(t); }
    }
  }
  const maxDepth = Math.max(0, ...Object.values(depth));
  for (const n of graph.nodes) if (depth[n.id] === undefined) depth[n.id] = maxDepth; // unreachable, park at the end
  if (depth.__end__ !== undefined) depth.__end__ = Math.max(depth.__end__, maxDepth); // end always last
  const columns = {};
  for (const n of graph.nodes) (columns[depth[n.id]] = columns[depth[n.id]] || []).push(n.id);
  const height = Math.max(...Object.values(columns).map((c) => c.length)) * ROW + PAD * 2;
  const pos = {};
  for (const [d, ids] of Object.entries(columns)) {
    const top = (height - ids.length * ROW) / 2 + ROW / 2;
    ids.forEach((id, i) => { pos[id] = { x: PAD + NODE_W / 2 + Number(d) * COL, y: top + i * ROW }; });
  }
  return { pos, depth, width: PAD * 2 + NODE_W + (Object.keys(columns).length - 1) * COL, height };
}

function edgePath(e, { pos, depth }) {
  const a = pos[e.source];
  const b = pos[e.target];
  const forward = depth[e.target] > depth[e.source];
  if (forward) {
    const x1 = a.x + NODE_W / 2;
    const x2 = b.x - NODE_W / 2;
    const mid = (x1 + x2) / 2;
    return `M ${x1} ${a.y} C ${mid} ${a.y}, ${mid} ${b.y}, ${x2} ${b.y}`;
  }
  // return edge: leave the bottom of the source, curve under, arrive at the bottom of the target
  const y1 = a.y + NODE_H / 2;
  const y2 = b.y + NODE_H / 2;
  const dip = Math.max(y1, y2) + 24 + Math.abs(a.x - b.x) / 14;
  return `M ${a.x} ${y1} C ${a.x} ${dip}, ${b.x} ${dip}, ${b.x} ${y2}`;
}

function Diagram({ graph }) {
  const l = layout(graph);
  return (
    <div className="diagram">
      <svg viewBox={`0 0 ${l.width} ${l.height}`} role="img" aria-label={graph.name} style={{ maxWidth: l.width }}>
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
          </marker>
        </defs>
        {graph.edges.map((e) => (
          <path key={`${e.source}-${e.target}`} d={edgePath(e, l)} className={e.conditional ? "edge conditional" : "edge"} markerEnd="url(#arrow)" />
        ))}
        {graph.nodes.map((n) => {
          const terminal = n.id.startsWith("__");
          const p = l.pos[n.id];
          return (
            <g key={n.id} transform={`translate(${p.x}, ${p.y})`}>
              {terminal ? <circle r={12} className="node terminal" /> : <rect x={-NODE_W / 2} y={-NODE_H / 2} width={NODE_W} height={NODE_H} rx={8} className="node" />}
              <text y={terminal ? 26 : 4} textAnchor="middle" className={terminal ? "node-label small" : "node-label"}>{label(n.id)}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// Static drawings of every agent graph as the backend defines them, so they cannot drift from the code.
export default function GraphView() {
  const [graphs, setGraphs] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/graph")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`API returned ${r.status}`))))
      .then(setGraphs)
      .catch((e) => setError(`Could not load the graphs: ${e.message}`));
  }, []);

  if (error) return <div className="error">{error}</div>;
  if (!graphs) return <section className="detail"><p className="empty">Loading the graphs…</p></section>;

  return (
    <>
      <p className="legend-line"><span className="swatch-cond" /> dashed arrow: conditional edge, chosen at run time; arrows curving underneath return control to the model node</p>
      {graphs.map((g) => (
        <section key={g.name} className="graph-block">
          <h3 className="graph-heading">{g.name}</h3>
          <p className="meta">{g.description}</p>
          <Diagram graph={g} />
          <ul className="node-notes">
            {g.nodes.filter((n) => !n.id.startsWith("__")).map((n) => (
              <li key={n.id}><code>{label(n.id)}</code><span>{n.description || "—"}</span></li>
            ))}
          </ul>
        </section>
      ))}
    </>
  );
}
