import type { GraphNode } from "../types";

const toolBadge = (tool: string) => {
  if (["search_faq", "get_account_overview", "get_payment_methods"].includes(tool))
    return <span className="badge badge-read">read</span>;
  if (["calculate_payoff_quote", "validate_payment_proposal"].includes(tool))
    return <span className="badge badge-proposal">proposal</span>;
  return <span className="badge badge-execution">execution</span>;
};

export function NodeDetails({ node }: { node: GraphNode | null }) {
  if (!node) {
    return (
      <div className="card" style={{ minHeight: 200 }}>
        <div className="card-title">Node Details</div>
        <p style={{ color: "var(--text-muted)", fontSize: 13 }}>
          Click a node in the graph to inspect its contract, tools, and rules.
        </p>
      </div>
    );
  }

  return (
    <div className="card node-detail">
      <div className="card-title">{node.label.replace(/\n/g, " ")}</div>

      <div className="field">
        <div className="field-label">Description</div>
        <div className="field-value">{node.desc}</div>
      </div>

      {node.contract && (
        <>
          <div className="field">
            <div className="field-label">Allowed Inputs</div>
            <div className="field-value">{node.contract.allowed_inputs.join(", ")}</div>
          </div>
          <div className="field">
            <div className="field-label">Writable State</div>
            <div className="field-value">{node.contract.writable_state.join(", ")}</div>
          </div>
          <div className="field">
            <div className="field-label">Tool Authority</div>
            <div className="field-value">{node.contract.tool_authority.join(", ")}</div>
          </div>
          <div className="field">
            <div className="field-label">Required Exits</div>
            <div className="field-value">{node.contract.required_exits.join(", ")}</div>
          </div>
        </>
      )}

      {node.tools && (
        <div className="field">
          <div className="field-label">Tools</div>
          <ul className="tool-list">
            {node.tools.map(t => <li key={t}>{toolBadge(t)} {t}</li>)}
          </ul>
        </div>
      )}

      {node.rules && (
        <div className="field">
          <div className="field-label">Rules</div>
          <ul className="rule-list">
            {node.rules.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}
