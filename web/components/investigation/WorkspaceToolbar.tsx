"use client";

import { useInvestigation } from "@/lib/investigation-context";
import { useLang } from "@/lib/i18n";

const STATUS_COLOR: Record<string, string> = {
  in_progress: "var(--amber)",
  awaiting_auditor: "var(--steel)",
  completed: "var(--forest)",
  stopped: "var(--slate)",
};

export default function WorkspaceToolbar() {
  const { investigation, stepping, runNextStep, runToCompletion } = useInvestigation();
  const { t } = useLang();
  if (!investigation) return null;

  const done = investigation.status === "completed" || investigation.status === "stopped";
  const color = STATUS_COLOR[investigation.status] ?? "var(--text-2)";
  const statusLabel = t(`toolbar.${investigation.status}`);

  return (
    <section
      className="mb-6 flex flex-col gap-3 border rounded-sm px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
      style={{ borderColor: "var(--hairline)", background: "var(--ink-1)" }}
    >
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span
            className="h-1.5 w-1.5 rounded-full"
            style={{ background: color, animation: investigation.status === "in_progress" ? "pulse-dot 1.4s ease-in-out infinite" : undefined }}
            aria-hidden
          />
          <span className="text-[10px] font-semibold tracking-[0.12em] uppercase" style={{ color }}>
            {statusLabel}
          </span>
        </div>
        <p className="mt-1 text-[12.5px] leading-snug line-clamp-2" style={{ color: "var(--text-1)" }} title={investigation.objective}>
          {investigation.objective}
        </p>
      </div>

      <div className="flex shrink-0 gap-2">
        <button
          onClick={() => void runNextStep()}
          disabled={stepping || done}
          className="rounded-sm border px-4 py-2 text-xs font-semibold tracking-[0.08em] uppercase transition-colors disabled:opacity-40"
          style={{ borderColor: "var(--amber)", color: "var(--amber)", background: "var(--amber-glow)" }}
        >
          {stepping ? t("toolbar.working") : t("toolbar.advance")}
        </button>
        <button
          onClick={() => void runToCompletion()}
          disabled={stepping || done}
          className="rounded-sm border px-4 py-2 text-xs font-semibold tracking-[0.08em] uppercase transition-colors disabled:opacity-40"
          style={{ borderColor: "var(--hairline-strong)", color: "var(--text-1)", background: "var(--ink-2)" }}
        >
          {t("toolbar.runToEnd")}
        </button>
      </div>
    </section>
  );
}
