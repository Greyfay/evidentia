"use client";

import { useInvestigation } from "@/lib/investigation-context";
import type { TimelineEventKind } from "@/lib/investigation-types";

const KIND_META: Record<TimelineEventKind, { icon: string; color: string; label: string }> = {
  hypothesis_created: { icon: "✦", color: "var(--steel)", label: "Hypothesis proposed" },
  tool_selected: { icon: "→", color: "var(--text-2)", label: "Tool selected" },
  tool_result: { icon: "✓", color: "var(--forest)", label: "Tool result" },
  counter_evidence: { icon: "⚡", color: "var(--amber)", label: "Self-challenge" },
  hypothesis_resolved: { icon: "◆", color: "var(--brick)", label: "Hypothesis resolved" },
  auditor_message: { icon: "»", color: "var(--steel)", label: "Auditor" },
  assistant_reply: { icon: "«", color: "var(--text-1)", label: "Agent" },
  stopped: { icon: "■", color: "var(--slate)", label: "Stopped" },
  completed: { icon: "●", color: "var(--forest)", label: "Completed" },
};

export default function InvestigationTimeline() {
  const { investigation } = useInvestigation();
  if (!investigation) return null;

  const events = [...investigation.timeline].sort((a, b) => Date.parse(a.at) - Date.parse(b.at));

  return (
    <section className="mb-10">
      <h2 className="text-[11px] tracking-[0.16em] uppercase mb-3" style={{ color: "var(--text-2)" }}>
        6 · Investigation timeline
      </h2>
      {events.length === 0 ? (
        <p className="text-xs" style={{ color: "var(--text-2)" }}>No events yet — run the first step.</p>
      ) : (
        <ol className="relative flex flex-col gap-4 pl-5" style={{ borderLeft: "1.5px solid var(--hairline-strong)" }}>
          {events.map((e, i) => {
            const meta = KIND_META[e.kind] ?? { icon: "•", color: "var(--text-2)", label: e.kind };
            return (
              <li key={i} className="relative" style={{ animation: "rise-in 220ms ease-out both", animationDelay: `${Math.min(i, 20) * 20}ms` }}>
                <span
                  className="absolute -left-[26px] top-0 flex h-4 w-4 items-center justify-center rounded-full text-[9px]"
                  style={{ background: "var(--ink-0)", border: `1.5px solid ${meta.color}`, color: meta.color }}
                  aria-hidden
                >
                  {meta.icon}
                </span>
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="text-[10.5px] font-semibold tracking-[0.05em] uppercase" style={{ color: meta.color }}>
                    {meta.label}
                  </span>
                  {e.tool_name && (
                    <span className="font-mono text-[10.5px]" style={{ color: "var(--text-2)" }}>
                      {e.tool_name}
                    </span>
                  )}
                  {e.hypothesis_id && (
                    <span className="font-mono text-[10px]" style={{ color: "var(--text-2)" }}>
                      {e.hypothesis_id}
                    </span>
                  )}
                  <span className="ml-auto font-mono text-[9.5px]" style={{ color: "var(--text-2)" }}>
                    {new Date(e.at).toLocaleTimeString("en-GB", { timeZone: "UTC", hour: "2-digit", minute: "2-digit", second: "2-digit" })} UTC
                  </span>
                </div>
                {e.detail && (
                  <p className="mt-1 text-[12.5px] leading-relaxed" style={{ color: "var(--text-1)" }}>
                    {e.detail}
                  </p>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
