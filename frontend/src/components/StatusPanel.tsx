import { IMPLEMENTATION } from "../data";

const pillClass = (s: string) => `status-pill pill-${s}`;

export function StatusPanel() {
  return (
    <div>
      <div className="card">
        <div className="card-title">Current Implementation — M1 + M2 core + M4 chat</div>
        <p style={{ fontSize: 13, color: "var(--text-dim)", marginBottom: 20 }}>
          The core graph, compliance engine, Temporal workflows, and web chat channel are implemented.
          The full suite reports 247 passed and 5 skipped. Mock services are running. LLM integration is
          wired but needs OpenAI credits for live responses.
        </p>

        <div className="status-grid">
          {IMPLEMENTATION.map(item => (
            <div key={item.component} className="status-item">
              <span className={pillClass(item.status)}>{item.status}</span>
              <div className="name">{item.component}</div>
              <div className="detail">{item.detail}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="card-title">How to Run Locally — $0 Cost</div>
        <div style={{ fontSize: 13, color: "var(--text-dim)", lineHeight: 1.8 }}>
          <p><strong>1. Start everything:</strong></p>
          <pre style={{
            background: "var(--bg)", border: "1px solid var(--border)",
            borderRadius: 8, padding: 12, margin: "8px 0 16px",
            fontFamily: "'SF Mono', monospace", fontSize: 12, overflowX: "auto"
          }}>
{`cd agentic-servicing-platform
./start.sh`}
          </pre>

          <p><strong>2. Run tests:</strong></p>
          <pre style={{
            background: "var(--bg)", border: "1px solid var(--border)",
            borderRadius: 8, padding: 12, margin: "8px 0 16px",
            fontFamily: "'SF Mono', monospace", fontSize: 12, overflowX: "auto"
          }}>
{`source .venv/bin/activate
pytest -v    # 247 passed, 5 skipped`}
          </pre>

          <p><strong>3. Interactive CLI:</strong></p>
          <pre style={{
            background: "var(--bg)", border: "1px solid var(--border)",
            borderRadius: 8, padding: 12, margin: "8px 0 16px",
            fontFamily: "'SF Mono', monospace", fontSize: 12, overflowX: "auto"
          }}>
{`python -m taylor.runtime.cli --no-llm    # free, deterministic mode
python -m taylor.runtime.cli             # needs OpenAI credits`}
          </pre>

          <p><strong>4. Mock services (running in Docker):</strong></p>
          <ul style={{ paddingLeft: 20, lineHeight: 1.8 }}>
            <li>FAC API: <code style={{ color: "var(--blue)" }}>http://localhost:9000</code></li>
            <li>Payment Provider: <code style={{ color: "var(--blue)" }}>http://localhost:9001</code></li>
            <li>PostgreSQL: <code style={{ color: "var(--blue)" }}>localhost:5432</code></li>
            <li>Redis: <code style={{ color: "var(--blue)" }}>localhost:6379</code></li>
            <li>Jaeger UI: <code style={{ color: "var(--blue)" }}>http://localhost:16686</code></li>
          </ul>
        </div>
      </div>

      <div className="card">
        <div className="card-title">What Costs Money</div>
        <div style={{ fontSize: 13, color: "var(--text-dim)", lineHeight: 1.8 }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                <th style={{ textAlign: "left", padding: "8px 0", fontSize: 12 }}>Capability</th>
                <th style={{ textAlign: "left", padding: "8px 0", fontSize: 12 }}>Cost</th>
                <th style={{ textAlign: "left", padding: "8px 0", fontSize: 12 }}>Free Workaround</th>
              </tr>
            </thead>
            <tbody>
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                <td style={{ padding: "8px 0" }}>LLM-powered responses</td>
                <td style={{ padding: "8px 0", color: "var(--orange)" }}>$5-20/mo OpenAI</td>
                <td style={{ padding: "8px 0" }}><code>--no-llm</code> deterministic mode</td>
              </tr>
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                <td style={{ padding: "8px 0" }}>Real SMS (M3)</td>
                <td style={{ padding: "8px 0", color: "var(--orange)" }}>~$15/mo Twilio</td>
                <td style={{ padding: "8px 0" }}>Not yet implemented</td>
              </tr>
              <tr>
                <td style={{ padding: "8px 0" }}>Real voice (M5)</td>
                <td style={{ padding: "8px 0", color: "var(--orange)" }}>Varies</td>
                <td style={{ padding: "8px 0" }}>Not yet implemented</td>
              </tr>
            </tbody>
          </table>
          <p style={{ marginTop: 12, fontWeight: 600, color: "var(--green)" }}>
            Everything else — routing, safety boundaries, tools, state machine, tests, visualizer — works for $0.
          </p>
        </div>
      </div>
    </div>
  );
}
