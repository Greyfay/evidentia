"use client";

import { InvestigationProvider, useInvestigation } from "@/lib/investigation-context";
import UploadZone from "@/components/investigation/UploadZone";
import HypothesisBoard from "@/components/investigation/HypothesisBoard";
import CurrentHypothesisPanel from "@/components/investigation/CurrentHypothesisPanel";
import PlanStepper from "@/components/investigation/PlanStepper";
import AuditorPanel from "@/components/investigation/AuditorPanel";
import InvestigationTimeline from "@/components/investigation/InvestigationTimeline";
import InvestigationGraphView from "@/components/investigation/InvestigationGraphView";
import InvestigationEvidenceDrawer from "@/components/investigation/InvestigationEvidenceDrawer";

function AgentModeBadge() {
  const { agentStatus, usingFallback } = useInvestigation();
  if (usingFallback || !agentStatus) return null;
  const live = agentStatus.mode === "live";
  const parts = [
    agentStatus.openai.active ? "OpenAI" : null,
    agentStatus.cognee.active ? "Cognee" : null,
  ].filter(Boolean);
  const label = parts.length ? parts.join(" + ") : "deterministic";
  const color = live ? "var(--forest)" : "var(--amber)";
  return (
    <div
      className="mb-6 inline-flex items-center gap-2 rounded-sm border px-3 py-2 text-xs"
      style={{ borderColor: color, color }}
      title={`planner: ${agentStatus.planner}${agentStatus.openai.model ? ` · model: ${agentStatus.openai.model}` : ""}`}
    >
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: color }} />
      {live ? "Live" : agentStatus.mode === "partial" ? "Partial" : "Fallback"} · {label} · planner: {agentStatus.planner}
    </div>
  );
}

function InvestigateContent() {
  const { usingFallback, investigation } = useInvestigation();

  return (
    <main className="mx-auto w-full max-w-6xl px-5 sm:px-8 py-10 sm:py-14">
      <AgentModeBadge />
      {usingFallback && (
        <div
          className="mb-6 flex items-center gap-2 rounded-sm border px-3 py-2 text-xs"
          style={{ borderColor: "var(--amber-dim)", background: "var(--amber-glow)", color: "var(--amber)" }}
        >
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: "var(--amber)" }} />
          Investigation API unreachable — rendering the bundled demo fixture. Actions still work locally.
        </div>
      )}

      <header className="mb-10">
        <h1 className="text-[26px] sm:text-[32px] leading-tight mb-2" style={{ fontFamily: "var(--font-display)", color: "var(--text-0)" }}>
          Investigation workspace
        </h1>
        <p className="text-[13.5px] max-w-2xl leading-relaxed" style={{ color: "var(--text-1)" }}>
          Upload a dossier, hand the agent an objective, and watch it propose hypotheses, pick tools, self-challenge
          its own claims, and hand off anything it can&apos;t resolve to you.
        </p>
      </header>

      <UploadZone />

      {investigation && (
        <>
          <HypothesisBoard />
          <CurrentHypothesisPanel />
          <PlanStepper />
          <AuditorPanel />
          <InvestigationTimeline />
          <section>
            <h2 className="text-[11px] tracking-[0.16em] uppercase mb-3" style={{ color: "var(--text-2)" }}>
              7 · Evidence graph
            </h2>
            <InvestigationGraphView />
          </section>
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
