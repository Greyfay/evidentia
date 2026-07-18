"use client";

import { useCasesData } from "@/lib/data-context";

export default function EvidenceValue({
  evidenceId,
  children,
  className = "",
  title,
}: {
  evidenceId: string;
  children: React.ReactNode;
  className?: string;
  title?: string;
}) {
  const { openEvidence } = useCasesData();
  return (
    <button
      type="button"
      onClick={() => openEvidence(evidenceId)}
      title={title ?? "Jump to source evidence"}
      className={
        "group relative inline-flex items-baseline gap-1 border-b border-dashed border-amber/50 text-inherit " +
        "hover:border-amber hover:text-amber transition-colors cursor-pointer " +
        className
      }
      style={{ borderColor: "var(--amber-dim)" }}
    >
      {children}
      <svg
        aria-hidden
        viewBox="0 0 8 8"
        className="w-[7px] h-[7px] opacity-40 group-hover:opacity-90 transition-opacity translate-y-[-3px]"
        fill="none"
      >
        <path d="M1 7L7 1M7 1H2.5M7 1V5.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </button>
  );
}
