import type { Hypothesis } from "@/lib/investigation-types";
import HypothesisStatusPill from "./HypothesisStatusPill";
import { HYPOTHESIS_STATUS_META } from "@/lib/format";

export default function HypothesisCard({
  h,
  rank,
  active,
  onSelect,
}: {
  h: Hypothesis;
  rank: number;
  active: boolean;
  onSelect: () => void;
}) {
  const meta = HYPOTHESIS_STATUS_META[h.status];
  return (
    <button
      onClick={onSelect}
      className="group relative flex flex-col gap-3 border rounded-sm p-4 text-left transition-all hover:-translate-y-[1px]"
      style={{
        background: active ? "var(--ink-2)" : "var(--ink-1)",
        borderColor: active ? meta.border : "var(--hairline)",
        animation: "rise-in 260ms ease-out both",
      }}
    >
      <span className="absolute left-0 top-4 bottom-4 w-[3px] rounded-r-sm" style={{ background: meta.color }} aria-hidden />
      <div className="pl-3 flex items-start justify-between gap-3">
        <span className="font-mono text-[10px]" style={{ color: "var(--text-2)" }}>
          #{rank} · {h.category.replace(/_/g, " ")}
        </span>
        <HypothesisStatusPill status={h.status} />
      </div>
      <p className="pl-3 text-[13.5px] leading-snug" style={{ color: "var(--text-0)" }}>
        {h.claim}
      </p>
      <div className="pl-3 flex items-center justify-between text-[10px]" style={{ color: "var(--text-2)" }}>
        <span className="uppercase tracking-[0.08em]">{h.priority} priority</span>
        {h.candidate_exposure && (
          <span className="font-mono mono-num" style={{ color: "var(--text-1)" }}>
            {h.candidate_exposure.amount} {h.candidate_exposure.currency}
          </span>
        )}
      </div>
    </button>
  );
}
