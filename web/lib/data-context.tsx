"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";
import sampleDocument from "@/cases.sample.json";
import type { CasesDocument, Case, Evidence } from "./types";

type WorkflowState = "idle" | "uploading" | "compiling" | "ready" | "error";

interface EvidenceHit {
  evidence: Evidence;
  caseId: string;
  caseTitle: string;
}

interface DataContextValue {
  document: CasesDocument | null;
  state: WorkflowState;
  error: string | null;
  uploadAndCompile: (file: File) => Promise<void>;
  getCase: (caseId: string) => Case | undefined;
  resolveEvidence: (evidenceId: string) => EvidenceHit | undefined;
  activeEvidenceId: string | null;
  openEvidence: (evidenceId: string) => Promise<void>;
  closeEvidence: () => void;
  submitReview: (caseId: string) => Promise<void>;
}

const DataContext = createContext<DataContextValue | null>(null);
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${body}`);
  }
  return response.json() as Promise<T>;
}

function buildEvidenceIndex(doc: CasesDocument | null): Map<string, EvidenceHit> {
  const index = new Map<string, EvidenceHit>();
  for (const c of doc?.cases ?? []) {
    const evidence = [
      ...c.evidence_chain.flatMap((step) => step.evidence),
      ...c.counter_tests.flatMap((test) => test.evidence),
    ];
    for (const item of evidence) {
      index.set(item.evidence_id, { evidence: item, caseId: c.case_id, caseTitle: c.title });
    }
  }
  return index;
}

export function CasesProvider({ children }: { children: React.ReactNode }) {
  const [document, setDocument] = useState<CasesDocument | null>(
    DEMO_MODE ? (sampleDocument as CasesDocument) : null,
  );
  const [state, setState] = useState<WorkflowState>(DEMO_MODE ? "ready" : "idle");
  const [error, setError] = useState<string | null>(null);
  const [activeEvidenceId, setActiveEvidenceId] = useState<string | null>(null);
  const [resolvedEvidence, setResolvedEvidence] = useState<Map<string, Evidence>>(new Map());

  const uploadAndCompile = useCallback(async (file: File) => {
    setError(null);
    setDocument(null);
    try {
      setState("uploading");
      const form = new FormData();
      form.append("file", file, file.name);
      form.append("control_ids", "split_payment");
      const uploaded = await api<{ investigation_id: string }>("/engagements/upload", {
        method: "POST",
        body: form,
      });

      setState("compiling");
      await api("/engagements/compile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          investigation_id: uploaded.investigation_id,
          control_ids: ["split_payment"],
        }),
      });
      const cases = await api<CasesDocument>("/cases", { cache: "no-store" });
      setDocument(cases);
      setState("ready");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      setState("error");
    }
  }, []);

  const evidenceIndex = useMemo(() => buildEvidenceIndex(document), [document]);
  const getCase = useCallback(
    (caseId: string) => document?.cases.find((c) => c.case_id === caseId),
    [document],
  );
  const resolveEvidence = useCallback(
    (evidenceId: string) => {
      const hit = evidenceIndex.get(evidenceId);
      const exact = resolvedEvidence.get(evidenceId);
      return hit && exact ? { ...hit, evidence: exact } : hit;
    },
    [evidenceIndex, resolvedEvidence],
  );
  const openEvidence = useCallback(async (evidenceId: string) => {
    setError(null);
    try {
      const evidence = await api<Evidence>(`/evidence/${encodeURIComponent(evidenceId)}`, {
        cache: "no-store",
      });
      setResolvedEvidence((current) => new Map(current).set(evidenceId, evidence));
      setActiveEvidenceId(evidenceId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      setState("error");
    }
  }, []);
  const closeEvidence = useCallback(() => setActiveEvidenceId(null), []);
  const submitReview = useCallback(async (caseId: string) => {
    setError(null);
    try {
      const reviewed = await api<Case>(`/cases/${encodeURIComponent(caseId)}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision: "escalate", note: "Reviewed in browser demo" }),
      });
      setDocument((current) => current && ({
        ...current,
        cases: current.cases.map((item) => item.case_id === caseId ? reviewed : item),
      }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      setState("error");
    }
  }, []);

  return (
    <DataContext.Provider value={{
      document, state, error, uploadAndCompile, getCase, resolveEvidence,
      activeEvidenceId, openEvidence, closeEvidence, submitReview,
    }}>
      {children}
    </DataContext.Provider>
  );
}

export function useCasesData() {
  const ctx = useContext(DataContext);
  if (!ctx) throw new Error("useCasesData must be used within CasesProvider");
  return ctx;
}
