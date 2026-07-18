"use client";

import { useInvestigation } from "@/lib/investigation-context";
import { useLang, localizeText } from "@/lib/i18n";
import EvidenceBadge from "./EvidenceBadge";
import type { TimelineEventKind } from "@/lib/investigation-types";

const KIND_META: Record<TimelineEventKind, { icon: string; color: string }> = {
  hypothesis_created: { icon: "✦", color: "var(--steel)" },
  tool_selected: { icon: "→", color: "var(--text-2)" },
  tool_result: { icon: "✓", color: "var(--forest)" },
  counter_evidence: { icon: "⚡", color: "var(--amber)" },
  hypothesis_resolved: { icon: "◆", color: "var(--brick)" },
  auditor_message: { icon: "»", color: "var(--steel)" },
  assistant_reply: { icon: "«", color: "var(--text-1)" },
  stopped: { icon: "■", color: "var(--slate)" },
  completed: { icon: "●", color: "var(--forest)" },
};

export default function InvestigationTimeline() {
  const { investigation } = useInvestigation();
  const { t, lang } = useLang();
  if (!investigation) return null;

  const events = [...investigation.timeline].sort((a, b) => Date.parse(a.at) - Date.parse(b.at));

  return (
    <details className="mt-8 border-t pt-6" style={{ borderColor: "var(--hairline)" }}>
      <summary className="cursor-pointer select-none text-[11px] tracking-[0.16em] uppercase" style={{ color: "var(--text-2)" }}>
        {t("log.title")}{events.length ? ` · ${events.length} ${t("log.events")}` : ""}
      </summary>
      {events.length === 0 ? (
        <p className="mt-3 text-xs" style={{ color: "var(--text-2)" }}>{t("log.none")}</p>
      ) : (
        <ol className="relative mt-4 flex flex-col gap-4 pl-5" style={{ borderLeft: "1.5px solid var(--hairline-strong)" }}>
          {events.map((e, i) => {
            const meta = KIND_META[e.kind] ?? { icon: "•", color: "var(--text-2)" };
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
                    {t(`kind.${e.kind}`)}
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
                    {localizeText(e.detail, lang)}
                  </p>
                )}
                {e.evidence_ids && e.evidence_ids.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {e.evidence_ids.map((id) => (
                      <EvidenceBadge key={id} evidenceId={id} />
                    ))}
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </details>
  );
}
