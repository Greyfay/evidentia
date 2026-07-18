import type {
  EngagementSummary,
  EvidenceView,
  Investigation,
  InvestigationGraph,
  TimelineEvent,
} from "./investigation-types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } finally {
    window.clearTimeout(timeout);
  }
}

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
  file: File,
): Promise<{ engagement_id: string; engagement: EngagementSummary }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetchWithTimeout(
    `${API_BASE}/engagements/upload`,
    { method: "POST", body: form },
    5 * 60 * 1000,
  );
  return json(res);
}

export async function createInvestigation(engagementId: string, objective: string): Promise<Investigation> {
  const res = await fetchWithTimeout(
    `${API_BASE}/investigations`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ engagement_id: engagementId, objective }),
    },
    30 * 1000,
  );
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
