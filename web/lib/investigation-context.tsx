"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import fixtureRaw from "@/investigation.sample.json";
import type {
  EngagementSummary,
  EvidenceView,
  Hypothesis,
  Investigation,
  InvestigationFixture,
  InvestigationGraph,
  TimelineEvent,
} from "./investigation-types";
import type { Evidence } from "./types";
import { formatLocator } from "./format";
import * as api from "./investigation-api";
import type { HypothesisAction } from "./investigation-api";

const fixture = fixtureRaw as unknown as InvestigationFixture;
const EMPTY_GRAPH: InvestigationGraph = { nodes: [], edges: [], available: false };

// Latest-value ref of each operation, so a failed request's "retry" can re-run
// it without a callback referencing itself (which the hooks linter rejects).
type Ops = {
  uploadDossier: (file: File) => void;
  startInvestigation: (objective: string) => void;
  runNextStep: () => void;
  runToCompletion: () => void;
  actOnHypothesis: (hypothesisId: string, action: HypothesisAction) => void;
  sendMessage: (message: string) => void;
};

interface InvestigationContextValue {
  // demoMode = the backend was never reachable (initial probe failed); the
  // whole flow runs on the bundled fixture and is labelled as a demo.
  demoMode: boolean;
  agentStatus: api.AgentStatus | null;
  engagement: EngagementSummary | null;
  investigation: Investigation | null;
  uploading: boolean;
  starting: boolean;
  stepping: boolean;
  // A live-mode request failed. Holds an i18n key; retry re-runs the operation.
  error: string | null;
  retry: (() => void) | null;
  clearError: () => void;
  selectedHypothesisId: string | null;
  selectHypothesis: (id: string) => void;
  uploadDossier: (file: File) => Promise<void>;
  startInvestigation: (objective: string) => Promise<void>;
  runNextStep: () => Promise<void>;
  runToCompletion: () => Promise<void>;
  actOnHypothesis: (hypothesisId: string, action: HypothesisAction) => Promise<void>;
  sendMessage: (message: string) => Promise<void>;
  activeEvidenceId: string | null;
  activeEvidence: EvidenceView | null;
  evidenceLoading: boolean;
  evidenceError: boolean;
  openEvidence: (evidenceId: string) => void;
  closeEvidence: () => void;
  graph: InvestigationGraph;
  reset: () => void;
}

const InvestigationContext = createContext<InvestigationContextValue | null>(null);

function nowIso(offsetSeconds: number): string {
  const base = Date.parse("2026-07-18T09:10:00Z");
  return new Date(base + offsetSeconds * 1000).toISOString();
}

// --- Demo-only helpers (only ever reached when demoMode is true) ---

function fixtureEvidenceView(id: string): EvidenceView | null {
  const ev = (fixture.evidence_index as Record<string, Evidence>)[id];
  if (!ev) return null;
  return {
    evidence_id: id,
    kind: ev.source_type,
    source: `${ev.source_path} · ${formatLocator(ev.locator)}`,
    snippet: ev.raw_value,
  };
}

function canned(action: HypothesisAction): { status: Hypothesis["status"]; detail: string } {
  switch (action) {
    case "dismiss":
      return { status: "dismissed", detail: "Auditor dismissed this line of inquiry." };
    case "submit":
      return { status: "submitted", detail: "Auditor submitted this finding for admission." };
    case "challenge":
      return { status: "active", detail: "Re-running self-challenge to search for an innocent explanation." };
    case "continue":
    default:
      return { status: "active", detail: "Auditor asked the agent to keep investigating." };
  }
}

function cannedReply(message: string): string {
  const m = message.toLowerCase();
  if (m.includes("why") || m.includes("warum")) {
    return "This line of inquiry was raised because the evidence graph surfaced an anomaly — a role or amount pattern that breaks an expected control. Every open suspicion traces back to a specific dossier record, not a hunch.";
  }
  if (m.includes("missing") || m.includes("evidence") || m.includes("fehlt") || m.includes("nachweis")) {
    return "Missing evidence is listed per line of inquiry under 'Still needed' — typically a corroborating document (declaration, approval log, bank statement) that the dossier does not contain.";
  }
  return "Noted. I'll factor that into the next tool selection and surface anything relevant in the log.";
}

export function InvestigationProvider({ children }: { children: React.ReactNode }) {
  const [demoMode, setDemoMode] = useState(false);
  const [agentStatus, setAgentStatus] = useState<api.AgentStatus | null>(null);
  const [engagement, setEngagement] = useState<EngagementSummary | null>(null);
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [uploading, setUploading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [stepping, setStepping] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState<(() => void) | null>(null);
  const [selectedHypothesisId, setSelectedHypothesisId] = useState<string | null>(null);
  const [activeEvidenceId, setActiveEvidenceId] = useState<string | null>(null);
  const [activeEvidence, setActiveEvidence] = useState<EvidenceView | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState(false);
  const [graph, setGraph] = useState<InvestigationGraph>(EMPTY_GRAPH);
  const stepIndexRef = useRef(0);
  const replyOffsetRef = useRef(0);
  const opsRef = useRef<Partial<Ops>>({});

  // Probe the backend once. Success → live mode (badge shows OpenAI/Cognee).
  // Failure → the backend is unreachable, so fall back to the labelled demo.
  useEffect(() => {
    let cancelled = false;
    api.getAgentStatus().then(
      (s) => {
        if (cancelled) return;
        setAgentStatus(s);
        setDemoMode(false);
      },
      () => {
        if (cancelled) return;
        setAgentStatus(null);
        setDemoMode(true);
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  const clearError = useCallback(() => {
    setError(null);
    setRetry(null);
  }, []);

  const fail = useCallback((key: string, retryFn: () => void) => {
    setError(key);
    setRetry(() => retryFn);
  }, []);

  const selectHypothesis = useCallback((id: string) => setSelectedHypothesisId(id), []);

  const pickDefaultSelection = useCallback((inv: Investigation) => {
    const priority = ["active", "awaiting_auditor", "proposed", "submitted", "dismissed", "insufficient"];
    const sorted = [...inv.hypotheses].sort(
      (a, b) => priority.indexOf(a.status) - priority.indexOf(b.status),
    );
    setSelectedHypothesisId(sorted[0]?.hypothesis_id ?? null);
  }, []);

  // Real relationship graph from the endpoint (live) or the fixture (demo).
  const refreshGraph = useCallback(
    async (investigationId: string) => {
      if (demoMode) {
        setGraph({ ...fixture.graph, available: fixture.graph.nodes.length > 0 });
        return;
      }
      try {
        const g = await api.getGraph(investigationId);
        setGraph({ ...g, available: g.available ?? g.nodes.length > 0 });
      } catch {
        setGraph(EMPTY_GRAPH);
      }
    },
    [demoMode],
  );

  const uploadDossier = useCallback(
    async (file: File) => {
      setUploading(true);
      clearError();
      try {
        if (demoMode) {
          setEngagement(fixture.engagement);
          return;
        }
        const result = await api.uploadEngagement(file);
        setEngagement({ ...result.engagement, engagement_id: result.engagement_id });
      } catch {
        fail("error.upload", () => opsRef.current.uploadDossier?.(file));
      } finally {
        setUploading(false);
      }
    },
    [demoMode, clearError, fail],
  );

  const startInvestigation = useCallback(
    async (objective: string) => {
      if (!engagement) return;
      setStarting(true);
      clearError();
      try {
        if (demoMode) {
          stepIndexRef.current = 0;
          const seed: Investigation = { ...fixture.steps[0], objective: objective || fixture.steps[0].objective };
          setInvestigation(seed);
          pickDefaultSelection(seed);
          void refreshGraph(seed.investigation_id);
          return;
        }
        const inv = await api.createInvestigation(engagement.engagement_id, objective);
        setInvestigation(inv);
        pickDefaultSelection(inv);
        void refreshGraph(inv.investigation_id);
      } catch {
        fail("error.start", () => opsRef.current.startInvestigation?.(objective));
      } finally {
        setStarting(false);
      }
    },
    [engagement, demoMode, clearError, fail, pickDefaultSelection, refreshGraph],
  );

  const runNextStep = useCallback(async () => {
    if (!investigation) return;
    setStepping(true);
    clearError();
    try {
      if (demoMode) {
        const next = Math.min(stepIndexRef.current + 1, fixture.steps.length - 1);
        stepIndexRef.current = next;
        const snapshot: Investigation = { ...fixture.steps[next], objective: investigation.objective };
        setInvestigation(snapshot);
        pickDefaultSelection(snapshot);
        void refreshGraph(snapshot.investigation_id);
        return;
      }
      const inv = await api.runNext(investigation.investigation_id);
      setInvestigation(inv);
      pickDefaultSelection(inv);
      void refreshGraph(inv.investigation_id);
    } catch {
      fail("error.step", () => opsRef.current.runNextStep?.());
    } finally {
      setStepping(false);
    }
  }, [investigation, demoMode, clearError, fail, pickDefaultSelection, refreshGraph]);

  const runToCompletion = useCallback(async () => {
    if (!investigation) return;
    setStepping(true);
    clearError();
    try {
      if (demoMode) {
        const last = fixture.steps.length - 1;
        stepIndexRef.current = last;
        const snapshot: Investigation = { ...fixture.steps[last], objective: investigation.objective };
        setInvestigation(snapshot);
        pickDefaultSelection(snapshot);
        void refreshGraph(snapshot.investigation_id);
        return;
      }
      const inv = await api.runToCompletion(investigation.investigation_id);
      setInvestigation(inv);
      pickDefaultSelection(inv);
      void refreshGraph(inv.investigation_id);
    } catch {
      fail("error.step", () => opsRef.current.runToCompletion?.());
    } finally {
      setStepping(false);
    }
  }, [investigation, demoMode, clearError, fail, pickDefaultSelection, refreshGraph]);

  const actOnHypothesisFn = useCallback(
    async (hypothesisId: string, action: HypothesisAction) => {
      if (!investigation) return;
      clearError();
      try {
        if (demoMode) {
          const { status, detail } = canned(action);
          replyOffsetRef.current += 12;
          setInvestigation((prev) => {
            if (!prev) return prev;
            const hypotheses = prev.hypotheses.map((h) =>
              h.hypothesis_id === hypothesisId ? { ...h, status } : h,
            );
            const event: TimelineEvent = {
              kind: action === "challenge" ? "counter_evidence" : "hypothesis_resolved",
              at: nowIso(replyOffsetRef.current),
              hypothesis_id: hypothesisId,
              detail,
            };
            return { ...prev, hypotheses, timeline: [...prev.timeline, event] };
          });
          return;
        }
        const inv = await api.actOnHypothesis(investigation.investigation_id, hypothesisId, action);
        setInvestigation(inv);
        void refreshGraph(inv.investigation_id);
      } catch {
        fail("error.decision", () => opsRef.current.actOnHypothesis?.(hypothesisId, action));
      }
    },
    [investigation, demoMode, clearError, fail, refreshGraph],
  );

  const sendMessageFn = useCallback(
    async (message: string) => {
      if (!investigation) return;
      clearError();
      try {
        if (demoMode) {
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
          return;
        }
        // Live: the endpoint returns the updated Investigation containing the new
        // auditor_message + grounded assistant_reply events. No client-side canning.
        const inv = await api.sendMessage(investigation.investigation_id, message);
        setInvestigation(inv);
      } catch {
        fail("error.message", () => opsRef.current.sendMessage?.(message));
      }
    },
    [investigation, demoMode, clearError, fail],
  );

  const openEvidence = useCallback(
    (id: string) => {
      setActiveEvidenceId(id);
      setEvidenceError(false);
      if (demoMode) {
        setActiveEvidence(fixtureEvidenceView(id));
        setEvidenceLoading(false);
        return;
      }
      if (!investigation) {
        setActiveEvidence(null);
        return;
      }
      setActiveEvidence(null);
      setEvidenceLoading(true);
      api.getInvestigationEvidence(investigation.investigation_id, id).then(
        (view) => {
          setActiveEvidence(view);
          setEvidenceLoading(false);
        },
        () => {
          setEvidenceError(true);
          setEvidenceLoading(false);
        },
      );
    },
    [demoMode, investigation],
  );

  const closeEvidence = useCallback(() => {
    setActiveEvidenceId(null);
    setActiveEvidence(null);
    setEvidenceLoading(false);
    setEvidenceError(false);
  }, []);

  // Keep the retry ref pointing at the latest operation callbacks.
  useEffect(() => {
    opsRef.current = {
      uploadDossier,
      startInvestigation,
      runNextStep,
      runToCompletion,
      actOnHypothesis: actOnHypothesisFn,
      sendMessage: sendMessageFn,
    };
  });

  const reset = useCallback(() => {
    setEngagement(null);
    setInvestigation(null);
    clearError();
    setSelectedHypothesisId(null);
    setActiveEvidenceId(null);
    setActiveEvidence(null);
    setGraph(EMPTY_GRAPH);
    stepIndexRef.current = 0;
    replyOffsetRef.current = 0;
  }, [clearError]);

  const value = useMemo<InvestigationContextValue>(
    () => ({
      demoMode,
      agentStatus,
      engagement,
      investigation,
      uploading,
      starting,
      stepping,
      error,
      retry,
      clearError,
      selectedHypothesisId,
      selectHypothesis,
      uploadDossier,
      startInvestigation,
      runNextStep,
      runToCompletion,
      actOnHypothesis: actOnHypothesisFn,
      sendMessage: sendMessageFn,
      activeEvidenceId,
      activeEvidence,
      evidenceLoading,
      evidenceError,
      openEvidence,
      closeEvidence,
      graph,
      reset,
    }),
    [
      demoMode,
      agentStatus,
      engagement,
      investigation,
      uploading,
      starting,
      stepping,
      error,
      retry,
      clearError,
      selectedHypothesisId,
      selectHypothesis,
      uploadDossier,
      startInvestigation,
      runNextStep,
      runToCompletion,
      actOnHypothesisFn,
      sendMessageFn,
      activeEvidenceId,
      activeEvidence,
      evidenceLoading,
      evidenceError,
      openEvidence,
      closeEvidence,
      graph,
      reset,
    ],
  );

  return <InvestigationContext.Provider value={value}>{children}</InvestigationContext.Provider>;
}

export function useInvestigation() {
  const ctx = useContext(InvestigationContext);
  if (!ctx) throw new Error("useInvestigation must be used within InvestigationProvider");
  return ctx;
}
