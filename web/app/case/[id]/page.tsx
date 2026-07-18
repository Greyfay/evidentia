"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useCasesData } from "@/lib/data-context";
import VerdictPill from "@/components/VerdictPill";
import SeverityTag from "@/components/SeverityTag";
import EvidenceChain from "@/components/EvidenceChain";
import CalculationBlock from "@/components/CalculationBlock";
import CounterTestsTable from "@/components/CounterTestsTable";
import EvidenceGraph from "@/components/EvidenceGraph";

function SectionLabel({ children, id }: { children: React.ReactNode; id?: string }) {
  return (
    <h2 id={id} className="text-[11px] tracking-[0.16em] uppercase mb-3 scroll-mt-8" style={{ color: "var(--text-2)" }}>
      {children}
    </h2>
  );
}

export default function CasePage() {
  const params = useParams<{ id: string }>();
  const { getCase, state } = useCasesData();
  const c = getCase(params.id);

  if (!c) {
    return (
      <main className="mx-auto w-full max-w-4xl px-5 sm:px-8 py-14 text-sm">
        <p style={{ color: "var(--text-2)" }}>
          {state === "uploading" || state === "compiling"
            ? "Loading engagement…"
            : "No case with this id in the compiled engagement."}
        </p>
        {state !== "uploading" && state !== "compiling" && (
          <Link href="/" className="inline-block mt-4 text-xs" style={{ color: "var(--amber)" }}>
            ← Back to case board
          </Link>
        )}
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-4xl px-5 sm:px-8 py-10 sm:py-14">
      <Link
        href="/"
        className="inline-flex items-center gap-1.5 text-xs mb-8 transition-colors"
        style={{ color: "var(--text-2)" }}
      >
        <span aria-hidden>←</span> Case board
      </Link>

      <header className="border-b pb-7 mb-8" style={{ borderColor: "var(--hairline)" }}>
        <div className="flex flex-wrap items-center gap-3 mb-4">
          <VerdictPill verdict={c.verdict} />
          <SeverityTag severity={c.severity} />
          <span className="font-mono text-[11px] ml-auto" style={{ color: "var(--text-2)" }}>
            {c.control_id} · v{c.control_version}
          </span>
        </div>
        <h1
          className="text-[26px] sm:text-[32px] leading-tight mb-3"
          style={{ fontFamily: "var(--font-display)", color: "var(--text-0)" }}
        >
          {c.title}
        </h1>
        <p className="text-[13px] mb-1" style={{ color: "var(--text-2)" }}>
          {c.assertion}
        </p>
        <p className="text-[15px] leading-relaxed mt-3" style={{ color: "var(--text-1)" }}>
          {c.narrative}
        </p>

        <a
          href="#calculation"
          className="mt-5 inline-flex items-baseline gap-2 border rounded-sm px-4 py-3 transition-colors hover:border-amber"
          style={{ borderColor: "var(--hairline-strong)", background: "var(--ink-1)" }}
        >
          <span className="text-[9px] tracking-[0.14em] uppercase" style={{ color: "var(--text-2)" }}>
            {c.financial_exposure.label} exposure
          </span>
          <span className="font-mono mono-num text-xl" style={{ color: "var(--text-0)" }}>
            {c.financial_exposure.amount}
          </span>
          <span className="text-xs" style={{ color: "var(--text-2)" }}>
            {c.financial_exposure.currency}
          </span>
        </a>
      </header>

      <section className="mb-10">
        <SectionLabel>Evidence chain</SectionLabel>
        <EvidenceChain steps={c.evidence_chain} />
      </section>

      <section id="calculation" className="mb-10">
        <SectionLabel>Reproducible calculation</SectionLabel>
        <CalculationBlock calc={c.calculation} />
      </section>

      <section className="mb-10">
        <SectionLabel>Counter-tests</SectionLabel>
        <CounterTestsTable tests={c.counter_tests} />
      </section>

      {(c.uncertainty || c.recommended_action) && (
        <section className="mb-10 grid gap-4 sm:grid-cols-2">
          {c.uncertainty && (
            <div className="border rounded-sm px-4 py-3" style={{ borderColor: "var(--amber-dim)", background: "var(--amber-glow)" }}>
              <div className="text-[9px] tracking-[0.14em] uppercase mb-1.5" style={{ color: "var(--amber)" }}>
                Uncertainty
              </div>
              <p className="text-xs leading-relaxed" style={{ color: "var(--text-1)" }}>
                {c.uncertainty}
              </p>
            </div>
          )}
          <div className="border rounded-sm px-4 py-3" style={{ borderColor: "var(--hairline)" }}>
            <div className="text-[9px] tracking-[0.14em] uppercase mb-1.5" style={{ color: "var(--text-2)" }}>
              Recommended action
            </div>
            <p className="text-xs leading-relaxed" style={{ color: "var(--text-0)" }}>
              {c.recommended_action}
            </p>
          </div>
        </section>
      )}

      <section>
        <SectionLabel>Evidence graph</SectionLabel>
        <EvidenceGraph c={c} />
      </section>
    </main>
  );
}
