"use client";

import { useInvestigation } from "@/lib/investigation-context";

export default function EvidenceBadge({ evidenceId }: { evidenceId: string }) {
  const { resolveEvidence, openEvidence } = useInvestigation();
  const hit = resolveEvidence(evidenceId);

  return (
    <button
      type="button"
      onClick={() => openEvidence(evidenceId)}
      className="inline-flex items-center gap-1 rounded-[3px] border px-1.5 py-0.5 font-mono text-[10px] transition-colors hover:border-amber"
      style={{ borderColor: "var(--hairline-strong)", color: "var(--text-1)", background: "var(--ink-2)" }}
      title={hit ? hit.raw_value : "Evidence record"}
    >
      <span className="w-1 h-1 rounded-full" style={{ background: "var(--amber)" }} aria-hidden />
      {evidenceId}
    </button>
  );
}
