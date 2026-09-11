import { useState } from "react";
import { simulateRoute } from "../data";
import type { SimResult } from "../types";

interface Props {
  onSimulate: (path: string[]) => void;
}

export function RouteSimulator({ onSimulate }: Props) {
  const [utterance, setUtterance] = useState("I want to pay $300");
  const [channel, setChannel] = useState("sms");
  const [auth, setAuth] = useState("verified");
  const [result, setResult] = useState<SimResult | null>(null);

  const handleSimulate = () => {
    const res = simulateRoute(utterance, channel, auth);
    setResult(res);
    onSimulate(res.path);
  };

  const routeClass = result?.preempted ? "preempt" : result?.blocked ? "blocked" : "ok";

  return (
    <div className="card">
      <div className="card-title">Route Simulator</div>
      <p style={{ fontSize: 12, color: "var(--text-dim)", marginBottom: 16 }}>
        Test how the deterministic router classifies an utterance. The graph will highlight
        the path the conversation takes.
      </p>

      <div className="sim-grid">
        <div className="sim-field">
          <label>Utterance</label>
          <input
            type="text"
            value={utterance}
            onChange={e => setUtterance(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleSimulate()}
            placeholder="e.g. I want to pay $300"
          />
        </div>
        <div className="sim-field">
          <label>Channel</label>
          <select value={channel} onChange={e => setChannel(e.target.value)}>
            <option value="sms">SMS</option>
            <option value="chat">Chat</option>
            <option value="voice">Voice</option>
          </select>
        </div>
        <div className="sim-field">
          <label>Auth Level</label>
          <select value={auth} onChange={e => setAuth(e.target.value)}>
            <option value="anonymous">Anonymous</option>
            <option value="verified">Verified</option>
            <option value="step_up">Step-Up</option>
          </select>
        </div>
      </div>

      <button className="btn-primary" onClick={handleSimulate}>
        Simulate Route
      </button>

      {result && (
        <div className="sim-result">
          <div className="route-label">Routed To</div>
          <div className={`route-value ${routeClass}`}>{result.route}</div>
          <div className="reason">{result.reason}</div>
          <div className="path">Path: {result.path.join(" → ")}</div>
        </div>
      )}

      <div style={{ marginTop: 16, fontSize: 11, color: "var(--text-muted)" }}>
        <strong>Try these:</strong>
        <ul style={{ marginTop: 6, paddingLeft: 16, lineHeight: 1.8 }}>
          <li>"I want to pay $300" — chat vs sms (chat blocks payment)</li>
          <li>"I'm filing for bankruptcy" — any channel (preempts to compliance)</li>
          <li>"What is my balance?" — anonymous vs verified (auth gate)</li>
          <li>"Can I settle my contract?" — arrangement route</li>
        </ul>
      </div>
    </div>
  );
}
