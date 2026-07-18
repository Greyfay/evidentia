"use client";

import { useMemo, useState } from "react";
import type { Case, Verdict } from "@/lib/types";
import { VERDICT_META } from "@/lib/format";
import CaseCard from "./CaseCard";

const ORDER: Verdict[] = ["CONFIRMED", "HUMAN_REVIEW", "DISMISSED", "REJECTED"];

export default function CaseBoard({ cases }: { cases: Case[] }) {
  const [filter, setFilter] = useState<Verdict | "ALL">("ALL");

  const counts = useMemo(() => {
    const c: Record<string, number> = { ALL: cases.length };
    for (const v of ORDER) c[v] = cases.filter((cs) => cs.verdict === v).length;
    return c;
  }, [cases]);

  const sorted = useMemo(
    () => [...cases].sort((a, b) => ORDER.indexOf(a.verdict) - ORDER.indexOf(b.verdict)),
    [cases],
  );
  const visible = filter === "ALL" ? sorted : sorted.filter((c) => c.verdict === filter);

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 mb-5">
        <FilterChip active={filter === "ALL"} onClick={() => setFilter("ALL")} label="All cases" count={counts.ALL} color="var(--text-1)" />
        {ORDER.map((v) => (
          <FilterChip
            key={v}
            active={filter === v}
            onClick={() => setFilter(v)}
            label={VERDICT_META[v].label}
            count={counts[v]}
            color={VERDICT_META[v].color}
          />
        ))}
      </div>

      {visible.length === 0 ? (
        <div
          className="border border-dashed rounded-sm px-6 py-10 text-center text-sm"
          style={{ borderColor: "var(--hairline-strong)", color: "var(--text-2)" }}
        >
          No cases carry this verdict in the compiled engagement.
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {visible.map((c, i) => (
            <div key={c.case_id} style={{ animationDelay: `${i * 30}ms` }}>
              <CaseCard c={c} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function FilterChip({
  active,
  onClick,
  label,
  count,
  color,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
  color: string;
}) {
  return (
    <button
      onClick={onClick}
      className="inline-flex items-center gap-2 rounded-sm border px-3 py-1.5 text-xs transition-colors"
      style={{
        borderColor: active ? color : "var(--hairline)",
        background: active ? "var(--ink-2)" : "transparent",
        color: active ? "var(--text-0)" : "var(--text-1)",
      }}
    >
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: color }} />
      {label}
      <span className="font-mono mono-num" style={{ color: "var(--text-2)" }}>
        {count}
      </span>
    </button>
  );
}
