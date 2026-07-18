"use client";

import { FormEvent, useState } from "react";
import { useCasesData } from "@/lib/data-context";
import EngagementHeader from "@/components/EngagementHeader";
import VerdictPill from "@/components/VerdictPill";
import CalculationBlock from "@/components/CalculationBlock";
import EvidenceChain from "@/components/EvidenceChain";

const STATE_LABELS = {
  idle: "Select the original dossier ZIP",
  uploading: "Uploading dossier…",
  compiling: "Compiling · split_payment control running…",
  ready: "Cases ready",
  error: "Error",
};

export default function HomePage() {
  const { document, state, error, uploadAndCompile, submitReview } = useCasesData();
  const [file, setFile] = useState<File | null>(null);
  const firstCase = document?.cases[0];
  const busy = state === "uploading" || state === "compiling";

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (file) void uploadAndCompile(file);
  };

  return (
    <main className="mx-auto w-full max-w-4xl px-5 sm:px-8 py-10 sm:py-14">
      <form
        onSubmit={submit}
        className="mb-10 border rounded-sm p-5"
        style={{ borderColor: "var(--hairline-strong)", background: "var(--ink-1)" }}
      >
        <div className="text-[10px] tracking-[0.16em] uppercase mb-3" style={{ color: "var(--amber)" }}>
          Live dossier upload
        </div>
        <div className="flex flex-col sm:flex-row gap-3">
          <input
            type="file"
            accept=".zip,application/zip"
            required
            disabled={busy}
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            className="min-w-0 flex-1 border rounded-sm px-3 py-2 text-sm"
            style={{ borderColor: "var(--hairline)", background: "var(--ink-2)" }}
          />
          <button
            type="submit"
            disabled={!file || busy}
            className="rounded-sm px-5 py-2 text-sm font-semibold disabled:opacity-40"
            style={{ background: "var(--amber)", color: "var(--ink-0)" }}
          >
            Upload and compile
          </button>
        </div>
        <div className="mt-3 flex items-center gap-2 text-xs" aria-live="polite">
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: state === "error" ? "var(--brick)" : "var(--amber)" }} />
          <span style={{ color: state === "error" ? "var(--brick)" : "var(--text-1)" }}>
            {STATE_LABELS[state]}
          </span>
        </div>
        {error && (
          <pre className="mt-3 whitespace-pre-wrap break-words rounded-sm border p-3 text-xs" style={{ borderColor: "var(--brick)", color: "var(--brick)" }}>
            {error}
          </pre>
        )}
      </form>

      {document && <EngagementHeader engagement={document.engagement} />}

      {state === "ready" && !firstCase && (
        <p className="text-sm" style={{ color: "var(--text-2)" }}>
          Compilation completed, but split_payment produced no cases.
        </p>
      )}

      {firstCase && (
        <article>
          <header className="mb-8 border-b pb-6" style={{ borderColor: "var(--hairline)" }}>
            <div className="mb-3 flex items-center justify-between gap-3">
              <VerdictPill verdict={firstCase.verdict} />
              <span className="font-mono text-[11px]" style={{ color: "var(--text-2)" }}>
                {firstCase.case_id}
              </span>
            </div>
            <h1 className="text-3xl" style={{ fontFamily: "var(--font-display)" }}>
              {firstCase.title}
            </h1>
          </header>

          <section className="mb-9">
            <h2 className="mb-3 text-[11px] uppercase tracking-[0.16em]" style={{ color: "var(--text-2)" }}>
              Calculation
            </h2>
            <CalculationBlock calc={firstCase.calculation} />
          </section>

          <section className="mb-9">
            <h2 className="mb-3 text-[11px] uppercase tracking-[0.16em]" style={{ color: "var(--text-2)" }}>
              Evidence
            </h2>
            <EvidenceChain steps={firstCase.evidence_chain} />
          </section>

          <button
            type="button"
            disabled={firstCase.reviewer_decision !== null}
            onClick={() => void submitReview(firstCase.case_id)}
            className="rounded-sm border px-4 py-2 text-sm disabled:opacity-50"
            style={{ borderColor: "var(--amber)", color: "var(--amber)" }}
          >
            {firstCase.reviewer_decision ? "Review submitted" : "Submit review action"}
          </button>
        </article>
      )}
    </main>
  );
}
