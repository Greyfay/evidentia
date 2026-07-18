"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import sampleDocument from "@/cases.sample.json";
import type { CasesDocument, Case, Evidence } from "./types";

interface EvidenceHit {
  evidence: Evidence;
  caseId: string;
  caseTitle: string;
}

interface DataContextValue {
  document: CasesDocument;
  loading: boolean;
  usingFallback: boolean;
  getCase: (caseId: string) => Case | undefined;
  resolveEvidence: (evidenceId: string) => EvidenceHit | undefined;
  activeEvidenceId: string | null;
  openEvidence: (evidenceId: string) => void;
  closeEvidence: () => void;
}

const DataContext = createContext<DataContextValue | null>(null);

function buildEvidenceIndex(doc: CasesDocument): Map<string, EvidenceHit> {
  const index = new Map<string, EvidenceHit>();
  for (const c of doc.cases) {
    for (const step of c.evidence_chain) {
      for (const ev of step.evidence) {
        index.set(ev.evidence_id, { evidence: ev, caseId: c.case_id, caseTitle: c.title });
      }
    }
    for (const test of c.counter_tests) {
      for (const ev of test.evidence) {
        if (!index.has(ev.evidence_id)) {
          index.set(ev.evidence_id, { evidence: ev, caseId: c.case_id, caseTitle: c.title });
        }
      }
    }
  }
  return index;
}

export function CasesProvider({ children }: { children: React.ReactNode }) {
  const [document, setDocument] = useState<CasesDocument>(sampleDocument as CasesDocument);
  const [loading, setLoading] = useState(true);
  const [usingFallback, setUsingFallback] = useState(true);
  const [activeEvidenceId, setActiveEvidenceId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/cases.json", { cache: "no-store" })
      .then((res) => {
        if (!res.ok) throw new Error(`status ${res.status}`);
        return res.json();
      })
      .then((data: CasesDocument) => {
        if (!cancelled && data && data.engagement && data.cases) {
          setDocument(data);
          setUsingFallback(false);
        }
      })
      .catch(() => {
        if (!cancelled) setUsingFallback(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const evidenceIndex = useMemo(() => buildEvidenceIndex(document), [document]);

  const getCase = useCallback(
    (caseId: string) => document.cases.find((c) => c.case_id === caseId),
    [document],
  );

  const resolveEvidence = useCallback(
    (evidenceId: string) => evidenceIndex.get(evidenceId),
    [evidenceIndex],
  );

  const openEvidence = useCallback((evidenceId: string) => setActiveEvidenceId(evidenceId), []);
  const closeEvidence = useCallback(() => setActiveEvidenceId(null), []);

  const value: DataContextValue = {
    document,
    loading,
    usingFallback,
    getCase,
    resolveEvidence,
    activeEvidenceId,
    openEvidence,
    closeEvidence,
  };

  return <DataContext.Provider value={value}>{children}</DataContext.Provider>;
}

export function useCasesData() {
  const ctx = useContext(DataContext);
  if (!ctx) throw new Error("useCasesData must be used within CasesProvider");
  return ctx;
}
