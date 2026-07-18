"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from "react";
import fixtureRaw from "@/investigation.sample.json";
import type {
  EngagementSummary,
  Hypothesis,
  Investigation,
  InvestigationFixture,
  InvestigationGraph,
  TimelineEvent,
} from "./investigation-types";
import type { Evidence } from "./types";
import * as api from "./investigation-api";
import type { HypothesisAction } from "./investigation-api";

const fixture = fixtureRaw as unknown as InvestigationFixture;

interface InvestigationContextValue {
  usingFallback: boolean;
  engagement: EngagementSummary | null;
  investigation: Investigation | null;
  uploading: boolean;
  starting: boolean;
  stepping: boolean;
  error: string | null;
  selectedHypothesisId: string | null;
  selectHypothesis: (id: string) => void;
  uploadDossier: (file: File) => Promise<void>;
  startInvestigation: (objective: string) => Promise<void>;
  runNextStep: () => Promise<void>;
  runToCompletion: () => Promise<void>;
  actOnHypothesis: (hypothesisId: string, action: HypothesisAction) => Promise<void>;
  sendMessage: (message: string) => Promise<void>;
  resolveEvidence: (evidenceId: string) => Evidence | undefined;
  activeEvidenceId: string | null;
  openEvidence: (evidenceId: string) => void;
  closeEvidence: () => void;
  graph: InvestigationGraph;
  reset: () => void;
}

const InvestigationContext = createContext<InvestigationContextValue | null>(null);

function nowIso(offsetSeconds: number): string {
  // Deterministic-ish clock for demo timeline entries created client-side.
  const base = Date.parse("2026-07-18T09:10:00Z");
  return new Date(base + offsetSeconds * 1000).toISOString();
}

function canned(hypothesisId: string, action: HypothesisAction): { verdict: TimelineEvent["kind"]; status: Hypothesis["status"]; detail: string } {
  switch (action) {
    case "dismiss":
      return { verdict: "hypothesis_resolved", status: "dismissed", detail: "Auditor dismissed this hypothesis." };
    case "submit":
      return { verdict: "hypothesis_resolved", status: "submitted", detail: "Auditor submitted this hypothesis for admission." };
    case "challenge":
      return { verdict: "counter_evidence", status: "active", detail: "Re-running self-challenge to search for an innocent explanation." };
    case "continue":
    default:
      return { verdict: "tool_selected", status: "active", detail: "Auditor asked the agent to keep investigating." };
  }
}

function cannedReply(message: string): string {
  const m = message.toLowerCase();
  if (m.includes("why")) {
    return "This hypothesis was proposed because the evidence graph surfaced an anomaly (a role or amount pattern that breaks an expected control) — every open hypothesis traces back to a specific dossier record, not a hunch.";
  }
  if (m.includes("missing") || m.includes("evidence")) {
    return "Missing evidence is listed per hypothesis under 'missing evidence' — typically a corroborating document (declaration, approval log, bank statement) that the dossier does not contain.";
  }
  return "Noted. I'll factor that into the next tool selection and surface anything relevant in the timeline.";
}

export function InvestigationProvider({ children }: { children: React.ReactNode }) {
  const [usingFallback, setUsingFallback] = useState(false);
  const [engagement, setEngagement] = useState<EngagementSummary | null>(null);
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [uploading, setUploading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [stepping, setStepping] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedHypothesisId, setSelectedHypothesisId] = useState<string | null>(null);
  const [activeEvidenceId, setActiveEvidenceId] = useState<string | null>(null);
  const stepIndexRef = useRef(0);
  const replyOffsetRef = useRef(0);

  const evidenceIndex = useMemo(() => fixture.evidence_index as Record<string, Evidence>, []);

  const resolveEvidence = useCallback(
    (evidenceId: string) => evidenceIndex[evidenceId],
    [evidenceIndex],
  );

  const selectHypothesis = useCallback((id: string) => setSelectedHypothesisId(id), []);
  const openEvidence = useCallback((id: string) => setActiveEvidenceId(id), []);
  const closeEvidence = useCallback(() => setActiveEvidenceId(null), []);

  const pickDefaultSelection = useCallback((inv: Investigation) => {
    const priority = ["active", "awaiting_auditor", "proposed", "submitted", "dismissed", "insufficient"];
    const sorted = [...inv.hypotheses].sort(
      (a, b) => priority.indexOf(a.status) - priority.indexOf(b.status),
    );
    setSelectedHypothesisId(sorted[0]?.hypothesis_id ?? null);
  }, []);

  const uploadDossier = useCallback(async (file: File) => {
    setUploading(true);
    setError(null);
    try {
      const result = await api.uploadEngagement(file);
      setEngagement(result.engagement);
      setUsingFallback(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Dossier upload failed");
      setEngagement({ ...fixture.engagement, name: `${file.name} (demo fixture — API unreachable)` });
      setUsingFallback(true);
    } finally {
      setUploading(false);
    }
  }, []);

  const startInvestigation = useCallback(
    async (objective: string) => {
      if (!engagement) return;
      setStarting(true);
      setError(null);
      try {
        if (usingFallback) throw new Error("fallback mode");
        const inv = await api.createInvestigation(engagement.engagement_id, objective);
        setInvestigation(inv);
        pickDefaultSelection(inv);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Investigation could not start");
        setUsingFallback(true);
        stepIndexRef.current = 0;
        const seed: Investigation = { ...fixture.steps[0], objective: objective || fixture.steps[0].objective };
        setInvestigation(seed);
        pickDefaultSelection(seed);
      } finally {
        setStarting(false);
      }
    },
    [engagement, usingFallback, pickDefaultSelection],
  );

  const runNextStep = useCallback(async () => {
    if (!investigation) return;
    setStepping(true);
    setError(null);
    try {
      if (usingFallback) throw new Error("fallback mode");
      const inv = await api.runNext(investigation.investigation_id);
      setInvestigation(inv);
      pickDefaultSelection(inv);
    } catch {
      setUsingFallback(true);
      const next = Math.min(stepIndexRef.current + 1, fixture.steps.length - 1);
      stepIndexRef.current = next;
      const snapshot: Investigation = { ...fixture.steps[next], objective: investigation.objective };
      setInvestigation(snapshot);
      pickDefaultSelection(snapshot);
    } finally {
      setStepping(false);
    }
  }, [investigation, usingFallback, pickDefaultSelection]);

  const runToCompletion = useCallback(async () => {
    if (!investigation) return;
    setStepping(true);
    setError(null);
    try {
      if (usingFallback) throw new Error("fallback mode");
      const inv = await api.runToCompletion(investigation.investigation_id);
      setInvestigation(inv);
      pickDefaultSelection(inv);
    } catch {
      setUsingFallback(true);
      const last = fixture.steps.length - 1;
      stepIndexRef.current = last;
      const snapshot: Investigation = { ...fixture.steps[last], objective: investigation.objective };
      setInvestigation(snapshot);
      pickDefaultSelection(snapshot);
    } finally {
      setStepping(false);
    }
  }, [investigation, usingFallback, pickDefaultSelection]);

  const actOnHypothesisFn = useCallback(
    async (hypothesisId: string, action: HypothesisAction) => {
      if (!investigation) return;
      setError(null);
      try {
        if (usingFallback) throw new Error("fallback mode");
        const inv = await api.actOnHypothesis(investigation.investigation_id, hypothesisId, action);
        setInvestigation(inv);
      } catch {
        setUsingFallback(true);
        const { verdict, status, detail } = canned(hypothesisId, action);
        replyOffsetRef.current += 12;
        setInvestigation((prev) => {
          if (!prev) return prev;
          const hypotheses = prev.hypotheses.map((h) =>
            h.hypothesis_id === hypothesisId ? { ...h, status } : h,
          );
          const event: TimelineEvent = {
            kind: verdict,
            at: nowIso(replyOffsetRef.current),
            hypothesis_id: hypothesisId,
            detail,
          };
          return { ...prev, hypotheses, timeline: [...prev.timeline, event] };
        });
      }
    },
    [investigation, usingFallback],
  );

  const sendMessageFn = useCallback(
    async (message: string) => {
      if (!investigation) return;
      setError(null);
      try {
        if (usingFallback) throw new Error("fallback mode");
        const inv = await api.sendMessage(investigation.investigation_id, message);
        setInvestigation(inv);
      } catch {
        setUsingFallback(true);
        replyOffsetRef.current += 6;
        const askAt = nowIso(replyOffsetRef.current);
        replyOffsetRef.current += 6;
        const replyAt = nowIso(replyOffsetRef.current);
        setInvestigation((prev) => {
          if (!prev) return prev;
          const events: TimelineEvent[] = [
            { kind: "auditor_message", at: askAt, detail: message },
            { kind: "assistant_reply", at: replyAt, detail: cannedReply(message) },
          ];
          return { ...prev, timeline: [...prev.timeline, ...events] };
        });
      }
    },
    [investigation, usingFallback],
  );

  const graph = useMemo<InvestigationGraph>(() => {
    if (fixture.graph.nodes.length) return fixture.graph;
    if (!investigation) return { nodes: [], edges: [] };
    const h = investigation.hypotheses.find((x) => x.hypothesis_id === selectedHypothesisId);
    if (!h) return { nodes: [], edges: [] };
    const nodes = [
      { id: h.hypothesis_id, label: h.subject, kind: "hypothesis" },
      ...h.supporting_evidence_ids.map((id) => ({ id, label: id, kind: "entity" })),
    ];
    const edges = h.supporting_evidence_ids.map((id) => ({ from: id, to: h.hypothesis_id }));
    return { nodes, edges };
  }, [investigation, selectedHypothesisId]);

  const reset = useCallback(() => {
    setEngagement(null);
    setInvestigation(null);
    setUsingFallback(false);
    setError(null);
    setSelectedHypothesisId(null);
    setActiveEvidenceId(null);
    stepIndexRef.current = 0;
    replyOffsetRef.current = 0;
  }, []);

  const value: InvestigationContextValue = {
    usingFallback,
    engagement,
    investigation,
    uploading,
    starting,
    stepping,
    error,
    selectedHypothesisId,
    selectHypothesis,
    uploadDossier,
    startInvestigation,
    runNextStep,
    runToCompletion,
    actOnHypothesis: actOnHypothesisFn,
    sendMessage: sendMessageFn,
    resolveEvidence,
    activeEvidenceId,
    openEvidence,
    closeEvidence,
    graph,
    reset,
  };

  return <InvestigationContext.Provider value={value}>{children}</InvestigationContext.Provider>;
}

export function useInvestigation() {
  const ctx = useContext(InvestigationContext);
  if (!ctx) throw new Error("useInvestigation must be used within InvestigationProvider");
  return ctx;
}
