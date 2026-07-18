"use client";

import { InvestigationProvider, useInvestigation } from "@/lib/investigation-context";
import { useLang } from "@/lib/i18n";
import UploadZone from "@/components/investigation/UploadZone";
import WorkspaceToolbar from "@/components/investigation/WorkspaceToolbar";
import DocketRail from "@/components/investigation/DocketRail";
import HypothesisFile from "@/components/investigation/HypothesisFile";
import InvestigationTimeline from "@/components/investigation/InvestigationTimeline";
import InvestigationEvidenceDrawer from "@/components/investigation/InvestigationEvidenceDrawer";

function AgentModeBadge() {
  const { agentStatus, demoMode } = useInvestigation();
  const { t } = useLang();
  if (demoMode || !agentStatus) return null;
  const live = agentStatus.mode === "live";
  const parts = [
    agentStatus.openai.active ? "OpenAI" : null,
    agentStatus.cognee.active ? "Cognee" : null,
  ].filter(Boolean);
  const label = parts.length ? parts.join(" + ") : "deterministic";
  const color = live ? "var(--forest)" : "var(--amber)";
  const modeLabel = live ? t("badge.live") : agentStatus.mode === "partial" ? t("badge.partial") : t("badge.fallback");
  return (
    <div
      className="inline-flex items-center gap-2 rounded-sm border px-3 py-1.5 text-xs"
      style={{ borderColor: color, color }}
      title={`${t("badge.planner")}: ${agentStatus.planner}${agentStatus.openai.model ? ` · ${agentStatus.openai.model}` : ""}`}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      {modeLabel} · {label} · {t("badge.planner")}: {agentStatus.planner}
    </div>
  );
}

function ErrorBanner() {
  const { error, retry, clearError } = useInvestigation();
  const { t } = useLang();
  if (!error) return null;
  return (
    <div
      role="alert"
      className="mb-6 flex flex-wrap items-center gap-3 rounded-sm border px-3 py-2.5 text-xs"
      style={{ borderColor: "var(--brick)", background: "var(--brick-glow)", color: "var(--text-0)" }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: "var(--brick)" }} />
      <span className="font-semibold" style={{ color: "var(--brick)" }}>{t("banner.error")}</span>
      <span style={{ color: "var(--text-1)" }}>{t(error)}</span>
      <div className="ml-auto flex gap-2">
        {retry && (
          <button
            onClick={() => retry()}
            className="rounded-sm border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.08em]"
            style={{ borderColor: "var(--brick)", color: "var(--brick)" }}
          >
            {t("action.retry")}
          </button>
        )}
        <button
          onClick={clearError}
          className="rounded-sm border px-2.5 py-1 text-[11px] uppercase tracking-[0.08em]"
          style={{ borderColor: "var(--hairline-strong)", color: "var(--text-2)" }}
        >
          {t("action.dismiss")}
        </button>
      </div>
    </div>
  );
}

function InvestigateContent() {
  const { demoMode, investigation } = useInvestigation();
  const { t } = useLang();

  return (
    <main className="mx-auto w-full max-w-6xl px-5 sm:px-8 py-10 sm:py-14">
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1
            className="text-[24px] sm:text-[30px] leading-tight"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-0)" }}
          >
            {t("page.title")}
          </h1>
          {!investigation && (
            <p className="mt-2 max-w-xl text-[13.5px] leading-relaxed" style={{ color: "var(--text-1)" }}>
              {t("page.intro")}
            </p>
          )}
        </div>
        <AgentModeBadge />
      </header>

      {demoMode && (
        <div
          className="mb-6 flex items-center gap-2 rounded-sm border px-3 py-2 text-xs"
          style={{ borderColor: "var(--amber-dim)", background: "var(--amber-glow)", color: "var(--amber)" }}
        >
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: "var(--amber)" }} />
          {t("banner.demo")}
        </div>
      )}

      <ErrorBanner />

      <UploadZone />

      {investigation && (
        <>
          <WorkspaceToolbar />
          <div className="grid gap-6 lg:grid-cols-[300px_minmax(0,1fr)]">
            <DocketRail />
            <HypothesisFile />
          </div>
          <InvestigationTimeline />
        </>
      )}

      <InvestigationEvidenceDrawer />
    </main>
  );
}

export default function InvestigatePage() {
  return (
    <InvestigationProvider>
      <InvestigateContent />
    </InvestigationProvider>
  );
}
