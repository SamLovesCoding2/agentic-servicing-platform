import { ROADMAP } from "../data";

const statusBadge = (s: string) => {
  if (s === "done") return <span className="status-pill pill-operational">Completed</span>;
  if (s === "in-progress") return <span className="status-pill pill-wired">In Progress</span>;
  return <span className="status-pill pill-planned">Planned</span>;
};

export function RoadmapPanel() {
  return (
    <div>
      <div className="card">
        <div className="card-title">Project Roadmap</div>
        <p style={{ fontSize: 13, color: "var(--text-dim)", marginBottom: 20 }}>
          Six milestones from core agent to full multi-channel production system.
          Milestone 1 is complete. Each milestone builds on the previous one.
        </p>
      </div>

      {ROADMAP.map(ms => (
        <div key={ms.name} className={`milestone ${ms.status}`}>
          <div className="milestone-header">
            {statusBadge(ms.status)}
            <span className="milestone-name">{ms.name}</span>
          </div>
          <div className="milestone-desc">{ms.desc}</div>
          <ul className="milestone-items">
            {ms.items.map((item, i) => <li key={i}>{item}</li>)}
          </ul>
        </div>
      ))}

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-title">Design Principles Enforced in Code</div>
        <ul className="rule-list" style={{ lineHeight: 2 }}>
          <li>Model proposes, code executes — LLM can only reach PROPOSED state</li>
          <li>Capability-based tool exposure — execution tools hidden until preconditions met</li>
          <li>UNKNOWN is not failure — timeout requires reconciliation, not retry</li>
          <li>Persist before success language — CONFIRMED must be in DB before success phrasing</li>
          <li>Versioned authorization — any bound field change invalidates consent</li>
          <li>Server-derived identity — model cannot supply customer_id or auth_level</li>
          <li>Transcript is evidence, not source of truth — business state in normalized DB fields</li>
          <li>Compliance phrases preempt all routing — handled before LLM sees the utterance</li>
          <li>Channel constraints are architectural — chat cannot reach payment tools</li>
          <li>File config &gt; DB config — immutable, versioned, replayable</li>
        </ul>
      </div>
    </div>
  );
}
