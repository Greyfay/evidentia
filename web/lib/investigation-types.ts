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
  structured_result: string;
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
}

export interface InvestigationFixture {
  engagement: EngagementSummary;
  evidence_index: Record<string, Evidence>;
  steps: Investigation[];
  graph: InvestigationGraph;
}
