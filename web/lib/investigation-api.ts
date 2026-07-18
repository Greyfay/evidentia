import type {
  EngagementSummary,
  EvidenceView,
  Investigation,
  InvestigationGraph,
  TimelineEvent,
} from "./investigation-types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json() as Promise<T>;
}

export interface AgentStatus {
  mode: "live" | "partial" | "fallback";
  planner: string;
  openai: { active: boolean; model: string | null };
  cognee: { active: boolean };
}

export async function getAgentStatus(): Promise<AgentStatus> {
  const res = await fetch(`${API_BASE}/agent-status`, { cache: "no-store" });
  return json(res);
}

export async function uploadEngagement(
  files: File[],
): Promise<{ engagement_id: string; engagement: EngagementSummary }> {
  const form = new FormData();
  // A single .zip is a packaged dossier; otherwise each file is an individual source
  // (PDF, Excel, CSV, …). The API accepts one or many under the "files" field.
  for (const file of files) form.append("files", file);
  const res = await fetch(`${API_BASE}/engagements/upload`, { method: "POST", body: form });
  return json(res);
}

export async function createInvestigation(engagementId: string, objective: string): Promise<Investigation> {
  const res = await fetch(`${API_BASE}/investigations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ engagement_id: engagementId, objective }),
  });
  return json(res);
}

export async function getInvestigation(id: string): Promise<Investigation> {
  const res = await fetch(`${API_BASE}/investigations/${id}`, { cache: "no-store" });
  return json(res);
}

export async function runNext(id: string): Promise<Investigation> {
  const res = await fetch(`${API_BASE}/investigations/${id}/run-next`, { method: "POST" });
  return json(res);
}

export async function runToCompletion(id: string): Promise<Investigation> {
  const res = await fetch(`${API_BASE}/investigations/${id}/run`, { method: "POST" });
  return json(res);
}

export async function getTimeline(id: string): Promise<TimelineEvent[]> {
  const res = await fetch(`${API_BASE}/investigations/${id}/timeline`, { cache: "no-store" });
  return json(res);
}

export async function getGraph(id: string): Promise<InvestigationGraph> {
  const res = await fetch(`${API_BASE}/investigations/${id}/graph`, { cache: "no-store" });
  return json(res);
}

export async function getInvestigationEvidence(
  investigationId: string,
  evidenceId: string,
): Promise<EvidenceView> {
  const res = await fetch(
    `${API_BASE}/investigations/${investigationId}/evidence/${evidenceId}`,
    { cache: "no-store" },
  );
  return json(res);
}

/** Absolute URL of the original uploaded file backing an evidence id — for an <iframe>,
 *  a text fetch, or a download link. Only meaningful for live (non-demo) investigations. */
export function sourceFileUrl(investigationId: string, evidenceId: string): string {
  return `${API_BASE}/investigations/${investigationId}/evidence/${evidenceId}/source-file`;
}

export type HypothesisAction = "dismiss" | "submit" | "continue" | "challenge";

export async function actOnHypothesis(
  investigationId: string,
  hypothesisId: string,
  action: HypothesisAction,
): Promise<Investigation> {
  const res = await fetch(
    `${API_BASE}/investigations/${investigationId}/hypotheses/${hypothesisId}/${action}`,
    { method: "POST" },
  );
  return json(res);
}

export async function sendMessage(investigationId: string, message: string): Promise<Investigation> {
  const res = await fetch(`${API_BASE}/investigations/${investigationId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  return json(res);
}
