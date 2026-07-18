import type { Verdict } from "@/lib/types";
import { VERDICT_META } from "@/lib/format";

export default function VerdictPill({ verdict, className = "" }: { verdict: Verdict; className?: string }) {
  const meta = VERDICT_META[verdict];
  return (
    <span
      className={`stamp inline-flex items-center gap-1.5 rounded-[3px] border px-2.5 py-1 text-[10px] font-semibold tracking-[0.1em] uppercase whitespace-nowrap ${className}`}
      style={{
        color: meta.color,
        borderColor: meta.border,
        background: meta.glow,
      }}
    >
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: meta.color }} />
      {meta.label}
    </span>
  );
}
