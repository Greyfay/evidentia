"use client";

import { useInvestigation } from "@/lib/investigation-context";
import { HYPOTHESIS_STATUS_META } from "@/lib/format";
import { useLang, localizeText, type Lang } from "@/lib/i18n";
import HypothesisStatusPill from "./HypothesisStatusPill";
import type { Hypothesis } from "@/lib/investigation-types";

const PRIORITY_RANK = { high: 0, medium: 1, low: 2 };
const OPEN_STATUSES = new Set(["active", "awaiting_auditor", "proposed"]);

export default function DocketRail() {
  const { investigation, selectedHypothesisId, selectHypothesis } = useInvestigation();
  const { t, lang } = useLang();
  if (!investigation) return null;

  const sorted = [...investigation.hypotheses].sort(
    (a, b) => PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority],
  );
  const firstOpen = sorted.find((h) => OPEN_STATUSES.has(h.status));

  return (
    <aside className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between">
        <h2 className="text-[11px] tracking-[0.16em] uppercase" style={{ color: "var(--text-2)" }}>
          {t("docket.title")}
        </h2>
        <span className="text-[11px]" style={{ color: "var(--text-2)" }}>
          {sorted.length}
        </span>
      </div>
      <ol className="flex flex-col gap-2">
        {sorted.map((h, i) => (
          <DocketItem
            key={h.hypothesis_id}
            h={h}
            rank={i + 1}
            active={h.hypothesis_id === selectedHypothesisId}
            startHere={h.hypothesis_id === firstOpen?.hypothesis_id}
            onSelect={() => selectHypothesis(h.hypothesis_id)}
            t={t}
            lang={lang}
          />
        ))}
      </ol>
    </aside>
  );
}

function DocketItem({
  h,
  rank,
  active,
  startHere,
  onSelect,
  t,
  lang,
}: {
  h: Hypothesis;
  rank: number;
  active: boolean;
  startHere: boolean;
  onSelect: () => void;
  t: (key: string, vars?: Record<string, string>) => string;
  lang: Lang;
}) {
  const meta = HYPOTHESIS_STATUS_META[h.status];
  return (
    <li>
      <button
        onClick={onSelect}
        aria-current={active}
        className="group relative flex w-full flex-col gap-2 rounded-sm border p-3 pl-4 text-left transition-colors"
        style={{
          background: active ? "var(--ink-2)" : "var(--ink-1)",
          borderColor: active ? meta.border : "var(--hairline)",
        }}
      >
        <span
          className="absolute left-0 top-2 bottom-2 w-[3px] rounded-r-sm transition-opacity"
          style={{ background: meta.color, opacity: active ? 1 : 0.45 }}
          aria-hidden
        />
        <div className="flex items-center justify-between gap-2">
          <span className="mono-num text-[10px]" style={{ color: "var(--text-2)" }}>
            {String(rank).padStart(2, "0")} · {h.subject}
          </span>
          <HypothesisStatusPill status={h.status} />
        </div>
        <p className="text-[12.5px] leading-snug" style={{ color: active ? "var(--text-0)" : "var(--text-1)" }}>
          {localizeText(h.claim, lang)}
        </p>
        <div className="flex items-center justify-between text-[10px]">
          {startHere ? (
            <span className="tracking-[0.1em] uppercase" style={{ color: "var(--amber)" }}>
              {t("docket.startHere")}
            </span>
          ) : (
            <span className="uppercase tracking-[0.08em]" style={{ color: "var(--text-2)" }}>
              {t("docket.priority", { p: t(`priority.${h.priority}`) })}
            </span>
          )}
          {h.candidate_exposure && (
            <span className="mono-num" style={{ color: "var(--text-1)" }}>
              {h.candidate_exposure.amount} {h.candidate_exposure.currency}
            </span>
          )}
        </div>
      </button>
    </li>
  );
}
