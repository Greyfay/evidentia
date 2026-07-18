import type { Evidence, EngagementCounts } from "./types";

export type HypothesisStatus =
  | "proposed"
  | "active"
  | "submitted"
  | "dismissed"
  | "insufficient"
  | "awaiting_auditor";

export type HypothesisPriority = "high" | "medium" | "low";

export interface CandidateExposure {
  amount: string;
  currency: string;
  label: string;
}

export interface Hypothesis {
  hypothesis_id: string;
  claim: string;
  category: string;
  status: HypothesisStatus;
  priority: HypothesisPriority;
  subject: string;
  supporting_evidence_ids: string[];
  contradicting_evidence_ids: string[];
  missing_evidence: string[];
  candidate_exposure: CandidateExposure | null;
  verdict_recommendation: string | null;
}

export interface Calculation {
  expression: string;
  result: string;
  sql?: string;
}

export interface CompletedAction {
  tool_name: string;
  // Backend returns the raw dict a tool produced; shape varies per tool.
  structured_result: Record<string, unknown> | string;
  evidence_ids: string[];
  calculation: Calculation | null;
  errors: string[];
  timestamp: string;
}

export type TimelineEventKind =
  | "hypothesis_created"
  | "tool_selected"
  | "tool_result"
  | "counter_evidence"
  | "hypothesis_resolved"
  | "auditor_message"
  | "assistant_reply"
  | "stopped"
  | "completed";

export interface TimelineEvent {
  kind: TimelineEventKind;
  at: string;
  hypothesis_id?: string;
  tool_name?: string;
  verdict?: string;
  detail?: string;
  // assistant_reply events may cite the evidence that grounds the answer.
  evidence_ids?: string[];
}

// Unified source record returned by the evidence endpoint (live) or mapped
// from the bundled fixture (demo). source = human-readable pointer; snippet =
// the exact source text/number.
export interface EvidenceView {
  evidence_id: string;
  kind: string;
  source: string;
  snippet: string;
}

export type InvestigationStatus =
  | "in_progress"
  | "awaiting_auditor"
  | "completed"
  | "stopped";

export interface Investigation {
  investigation_id: string;
  engagement_id: string;
  objective: string;
  status: InvestigationStatus;
  hypotheses: Hypothesis[];
  completed_actions: CompletedAction[];
  timeline: TimelineEvent[];
  questions_for_auditor: string[];
  evidence_ids: string[];
}

export interface EngagementSourceSummary {
  path: string;
  bytes: number;
  status: string;
}

export interface EngagementSummary {
  engagement_id: string;
  name: string;
  counts: EngagementCounts;
  source_files: EngagementSourceSummary[];
}

export interface GraphNode {
  id: string;
  label: string;
  kind: string;
}

export interface GraphEdge {
  from: string;
  to: string;
  label?: string;
}

export interface InvestigationGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  // Backend signals whether a real relationship graph was available (Cognee /
  // in-memory). Absent in the bundled fixture — treated as available there.
  available?: boolean;
}

export interface InvestigationFixture {
  engagement: EngagementSummary;
  evidence_index: Record<string, Evidence>;
  steps: Investigation[];
  graph: InvestigationGraph;
}
