"use client";

import { useInvestigation } from "@/lib/investigation-context";
import HypothesisCard from "./HypothesisCard";

const PRIORITY_RANK = { high: 0, medium: 1, low: 2 };

export default function HypothesisBoard() {
  const { investigation, selectedHypothesisId, selectHypothesis } = useInvestigation();
  if (!investigation) return null;

  const sorted = [...investigation.hypotheses].sort(
    (a, b) => PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority],
  );

  return (
    <section className="mb-10">
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-[11px] tracking-[0.16em] uppercase" style={{ color: "var(--text-2)" }}>
          2 · Agent brief — proposed investigation paths
        </h2>
        <span className="text-xs" style={{ color: "var(--text-2)" }}>
          {sorted.length} hypotheses
        </span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {sorted.map((h, i) => (
          <HypothesisCard
            key={h.hypothesis_id}
            h={h}
            rank={i + 1}
            active={h.hypothesis_id === selectedHypothesisId}
            onSelect={() => selectHypothesis(h.hypothesis_id)}
          />
        ))}
      </div>
    </section>
  );
}
