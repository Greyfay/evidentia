"use client";

import { useInvestigation } from "@/lib/investigation-context";
import HypothesisStatusPill from "./HypothesisStatusPill";
import EvidenceBadge from "./EvidenceBadge";

function EvidenceList({ ids, empty }: { ids: string[]; empty: string }) {
  if (!ids.length) {
    return <p className="text-xs" style={{ color: "var(--text-2)" }}>{empty}</p>;
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {ids.map((id) => (
        <EvidenceBadge key={id} evidenceId={id} />
      ))}
    </div>
  );
}

export default function CurrentHypothesisPanel() {
  const { investigation, selectedHypothesisId } = useInvestigation();
  const h = investigation?.hypotheses.find((x) => x.hypothesis_id === selectedHypothesisId);

  if (!investigation) return null;

  return (
    <section className="mb-10">
      <h2 className="text-[11px] tracking-[0.16em] uppercase mb-3" style={{ color: "var(--text-2)" }}>
        3 · Current hypothesis
      </h2>
      {!h ? (
        <p className="text-sm" style={{ color: "var(--text-2)" }}>Select a hypothesis above.</p>
      ) : (
        <div className="border rounded-sm p-5" style={{ borderColor: "var(--hairline)", background: "var(--ink-1)" }}>
          <div className="flex flex-wrap items-center gap-3 mb-3">
            <HypothesisStatusPill status={h.status} />
            <span className="font-mono text-[10.5px]" style={{ color: "var(--text-2)" }}>
              {h.category.replace(/_/g, " ")} · {h.subject}
            </span>
          </div>
          <p className="text-[15px] leading-relaxed mb-5" style={{ color: "var(--text-0)", fontFamily: "var(--font-display)" }}>
            {h.claim}
          </p>

          <div className="grid gap-5 sm:grid-cols-3 mb-5">
            <div>
              <div className="text-[10px] tracking-[0.14em] uppercase mb-2" style={{ color: "var(--forest)" }}>
                Supporting evidence
              </div>
              <EvidenceList ids={h.supporting_evidence_ids} empty="None gathered yet." />
            </div>
            <div>
              <div className="text-[10px] tracking-[0.14em] uppercase mb-2" style={{ color: "var(--brick)" }}>
                Contradicting evidence
              </div>
              <EvidenceList ids={h.contradicting_evidence_ids} empty="None found." />
            </div>
            <div>
              <div className="text-[10px] tracking-[0.14em] uppercase mb-2" style={{ color: "var(--text-2)" }}>
                Missing evidence
              </div>
              {h.missing_evidence.length ? (
                <ul className="flex flex-col gap-1">
                  {h.missing_evidence.map((m) => (
                    <li key={m} className="text-xs" style={{ color: "var(--text-1)" }}>
                      · {m}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs" style={{ color: "var(--text-2)" }}>Nothing outstanding.</p>
              )}
            </div>
          </div>

          <div className="flex flex-wrap items-end justify-between gap-4 pt-4 border-t" style={{ borderColor: "var(--hairline)" }}>
            <div>
              <div className="text-[9px] tracking-[0.12em] uppercase mb-1" style={{ color: "var(--text-2)" }}>
                Candidate exposure
              </div>
              {h.candidate_exposure ? (
                <div className="font-mono mono-num text-xl" style={{ color: "var(--text-0)" }}>
                  {h.candidate_exposure.amount}{" "}
                  <span className="text-[12px]" style={{ color: "var(--text-2)" }}>
                    {h.candidate_exposure.currency} · {h.candidate_exposure.label}
                  </span>
                </div>
              ) : (
                <span className="text-sm" style={{ color: "var(--text-2)" }}>Not yet computed</span>
              )}
            </div>
            {h.verdict_recommendation && (
              <p className="max-w-md text-right text-[12.5px] leading-relaxed" style={{ color: "var(--text-1)" }}>
                {h.verdict_recommendation}
              </p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
