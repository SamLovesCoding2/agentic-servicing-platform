// Shared types for the Salient Replica visualizer

export type NodeType = "control" | "subgraph" | "gate";
export type ToolClass = "read" | "proposal" | "execution";

export interface GraphNode {
  id: string;
  label: string;
  type: NodeType;
  x: number;
  y: number;
  r: number;
  color: string;
  desc: string;
  contract?: {
    allowed_inputs: string[];
    writable_state: string[];
    tool_authority: string[];
    required_exits: string[];
  };
  tools?: string[];
  rules?: string[];
}

export interface GraphEdge {
  from: string;
  to: string;
  label?: string;
  dashed?: boolean;
}

export interface SimResult {
  route: string;
  reason: string;
  preempted: boolean;
  blocked: boolean;
  path: string[];
}

export interface MilestoneItem {
  name: string;
  status: "done" | "in-progress" | "planned";
  desc: string;
  items: string[];
}

export interface ImplItem {
  component: string;
  status: "operational" | "wired" | "running" | "planned";
  detail: string;
}
