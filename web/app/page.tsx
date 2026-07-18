"use client";

import { useCasesData } from "@/lib/data-context";
import EngagementHeader from "@/components/EngagementHeader";
import SourceFileTable from "@/components/SourceFileTable";
import CaseBoard from "@/components/CaseBoard";

export default function HomePage() {
  const { document, usingFallback, loading } = useCasesData();

  return (
    <main className="mx-auto w-full max-w-6xl px-5 sm:px-8 py-10 sm:py-14">
      {!loading && usingFallback && (
        <div
          className="mb-6 flex items-center gap-2 rounded-sm border px-3 py-2 text-xs"
          style={{ borderColor: "var(--amber-dim)", background: "var(--amber-glow)", color: "var(--amber)" }}
        >
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: "var(--amber)" }} />
          No <span className="font-mono">/cases.json</span> found in public/ — rendering the bundled
          sample fixture.
        </div>
      )}

      <EngagementHeader engagement={document.engagement} />

      <section className="mb-12">
        <h2 className="text-[11px] tracking-[0.16em] uppercase mb-3" style={{ color: "var(--text-2)" }}>
          Source files
        </h2>
        <SourceFileTable files={document.engagement.source_files} />
      </section>

      <section>
        <div className="flex items-baseline justify-between mb-4">
          <h2 className="text-[11px] tracking-[0.16em] uppercase" style={{ color: "var(--text-2)" }}>
            Case board
          </h2>
          <span className="text-xs" style={{ color: "var(--text-2)" }}>
            prioritized by verdict
          </span>
        </div>
        <CaseBoard cases={document.cases} />
      </section>
    </main>
  );
}
