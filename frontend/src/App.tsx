import { useState } from "react";
import "./App.css";
import { NODES, EDGES } from "./data";
import type { GraphNode } from "./types";
import { GraphCanvas } from "./components/GraphCanvas";
import { NodeDetails } from "./components/NodeDetails";
import { RouteSimulator } from "./components/RouteSimulator";
import { StatusPanel } from "./components/StatusPanel";
import { RoadmapPanel } from "./components/RoadmapPanel";

type Tab = "graph" | "status" | "roadmap";

export default function App() {
  const [tab, setTab] = useState<Tab>("graph");
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [highlightPath, setHighlightPath] = useState<string[] | null>(null);

  const handleSelect = (id: string) => {
    const node = NODES.find(n => n.id === id) || null;
    setSelectedNode(node);
  };

  return (
    <div className="app">
      {/* Nav Bar */}
      <nav className="navbar">
        <div className="navbar-brand">
          <span className="dot" />
          Salient Replica
        </div>
        <div className="navbar-tabs">
          <button
            className={`navbar-tab ${tab === "graph" ? "active" : ""}`}
            onClick={() => setTab("graph")}
          >
            Graph
          </button>
          <button
            className={`navbar-tab ${tab === "status" ? "active" : ""}`}
            onClick={() => setTab("status")}
          >
            Implementation
          </button>
          <button
            className={`navbar-tab ${tab === "roadmap" ? "active" : ""}`}
            onClick={() => setTab("roadmap")}
          >
            Roadmap
          </button>
        </div>
        <span className="navbar-badge">131 tests passing</span>
      </nav>

      {/* Main Content */}
      <div className="main">
        {tab === "graph" && (
          <>
            <RouteSimulator onSimulate={setHighlightPath} />

            <div className="graph-layout">
              <div className="graph-canvas-wrap">
                <GraphCanvas
                  nodes={NODES}
                  edges={EDGES}
                  selectedId={selectedNode?.id ?? null}
                  highlightPath={highlightPath}
                  onSelect={handleSelect}
                />
                <div className="legend">
                  <div className="legend-row"><div className="legend-dot" style={{ background: "#8957e5" }} /> Routing / Control</div>
                  <div className="legend-row"><div className="legend-dot" style={{ background: "#2ea043" }} /> Read Tool</div>
                  <div className="legend-row"><div className="legend-dot" style={{ background: "#d29922" }} /> Proposal Tool</div>
                  <div className="legend-row"><div className="legend-dot" style={{ background: "#da3633" }} /> Execution Tool</div>
                  <div className="legend-row"><div className="legend-dot" style={{ background: "#1f6feb" }} /> Gate</div>
                </div>
              </div>

              <div className="graph-sidebar">
                <NodeDetails node={selectedNode} />
              </div>
            </div>
          </>
        )}

        {tab === "status" && <StatusPanel />}
        {tab === "roadmap" && <RoadmapPanel />}
      </div>
    </div>
  );
}
