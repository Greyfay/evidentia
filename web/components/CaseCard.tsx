import Link from "next/link";
import type { Case } from "@/lib/types";
import VerdictPill from "./VerdictPill";
import SeverityTag from "./SeverityTag";
import { VERDICT_META } from "@/lib/format";

export default function CaseCard({ c }: { c: Case }) {
  const meta = VERDICT_META[c.verdict];
  return (
    <Link
      href={`/case/${c.case_id}`}
      className="group relative flex flex-col justify-between gap-4 border rounded-sm p-4 transition-all hover:-translate-y-[1px]"
      style={{
        background: "var(--ink-1)",
        borderColor: "var(--hairline)",
        animation: "rise-in 260ms ease-out both",
      }}
      onMouseEnter={(e) => (e.currentTarget.style.borderColor = meta.border)}
      onMouseLeave={(e) => (e.currentTarget.style.borderColor = "var(--hairline)")}
    >
      <span
        className="absolute left-0 top-4 bottom-4 w-[3px] rounded-r-sm"
        style={{ background: meta.color }}
        aria-hidden
      />
      <div className="pl-3">
        <div className="flex items-start justify-between gap-3">
          <VerdictPill verdict={c.verdict} />
          <span className="font-mono text-[10px]" style={{ color: "var(--text-2)" }}>
            {c.control_id}
          </span>
        </div>
        <h3 className="mt-3 text-[15px] leading-snug" style={{ fontFamily: "var(--font-display)", color: "var(--text-0)" }}>
          {c.title}
        </h3>
        <p className="mt-1.5 text-[12.5px] leading-relaxed line-clamp-2" style={{ color: "var(--text-1)" }}>
          {c.narrative}
        </p>
      </div>
      <div className="pl-3 flex items-end justify-between">
        <SeverityTag severity={c.severity} />
        <div className="text-right">
          <div className="text-[9px] tracking-[0.12em] uppercase" style={{ color: "var(--text-2)" }}>
            {c.financial_exposure.label} exposure
          </div>
          <div className="font-mono mono-num text-[15px]" style={{ color: "var(--text-0)" }}>
            {c.financial_exposure.amount}{" "}
            <span className="text-[11px]" style={{ color: "var(--text-2)" }}>
              {c.financial_exposure.currency}
            </span>
          </div>
        </div>
      </div>
    </Link>
  );
}
