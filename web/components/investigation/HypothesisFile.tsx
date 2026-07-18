"use client";

import { useInvestigation } from "@/lib/investigation-context";
import { HYPOTHESIS_STATUS_META } from "@/lib/format";
import { useLang, localizeText } from "@/lib/i18n";
import HypothesisStatusPill from "./HypothesisStatusPill";
import EvidenceBadge from "./EvidenceBadge";
import AgentChecks from "./AgentChecks";
import DecisionBar from "./DecisionBar";
import InvestigationGraphView from "./InvestigationGraphView";
import type { Hypothesis } from "@/lib/investigation-types";

function EvidenceColumn({
  title,
  color,
  ids,
  empty,
}: {
  title: string;
  color: string;
  ids: string[];
  empty: string;
}) {
  return (
    <div>
      <div className="mb-2 text-[10px] tracking-[0.14em] uppercase" style={{ color }}>
        {title}
      </div>
      {ids.length ? (
        <div className="flex flex-wrap gap-1.5">
          {ids.map((id) => (
            <EvidenceBadge key={id} evidenceId={id} />
          ))}
        </div>
      ) : (
        <p className="text-xs" style={{ color: "var(--text-2)" }}>
          {empty}
        </p>
      )}
    </div>
  );
}

function Section({ title, aside, children }: { title: string; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section>
      <div className="mb-2.5 flex items-baseline justify-between">
        <h3 className="text-[11px] tracking-[0.16em] uppercase" style={{ color: "var(--text-2)" }}>
          {title}
        </h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

export default function HypothesisFile() {
  const { investigation, selectedHypothesisId } = useInvestigation();
  const { t, lang } = useLang();
  const h: Hypothesis | undefined = investigation?.hypotheses.find(
    (x) => x.hypothesis_id === selectedHypothesisId,
  );

  if (!investigation) return null;
  if (!h) {
    return (
      <p className="text-sm" style={{ color: "var(--text-2)" }}>
        {t("file.chooseInquiry")}
      </p>
    );
  }

  const meta = HYPOTHESIS_STATUS_META[h.status];

  return (
    <div className="flex flex-col gap-7">
      {/* Verdict banner — the signature: claim, recommended verdict, exposure */}
      <section
        className="relative overflow-hidden rounded-sm border p-5 pl-6"
        style={{ borderColor: meta.border, background: "var(--ink-1)" }}
      >
        <span className="absolute left-0 top-0 bottom-0 w-[4px]" style={{ background: meta.color }} aria-hidden />
        <div className="flex flex-wrap items-center gap-3">
          <HypothesisStatusPill status={h.status} />
          <span className="text-[10.5px] tracking-[0.08em] uppercase" style={{ color: meta.color }}>
            {t(`verdict.${h.status}`)}
          </span>
          <span className="text-[10.5px]" style={{ color: "var(--text-2)" }}>
            {h.category.replace(/_/g, " ")} · {h.subject}
          </span>
        </div>

        <p className="mt-3 text-[17px] leading-relaxed" style={{ color: "var(--text-0)", fontFamily: "var(--font-display)" }}>
          {localizeText(h.claim, lang)}
        </p>

        <div className="mt-4 flex flex-wrap items-end justify-between gap-4 border-t pt-4" style={{ borderColor: "var(--hairline)" }}>
          <div>
            <div className="text-[9px] tracking-[0.12em] uppercase" style={{ color: "var(--text-2)" }}>
              {t("file.amountAtRisk")}
            </div>
            {h.candidate_exposure ? (
              <div className="mono-num text-2xl" style={{ color: "var(--text-0)" }}>
                {h.candidate_exposure.amount}{" "}
                <span className="text-[13px]" style={{ color: "var(--text-2)" }}>
                  {h.candidate_exposure.currency} · {h.candidate_exposure.label}
                </span>
              </div>
            ) : (
              <div className="text-sm" style={{ color: "var(--text-2)" }}>{t("file.notComputed")}</div>
            )}
          </div>
          {h.verdict_recommendation && (
            <p className="max-w-md text-[12.5px] leading-relaxed" style={{ color: "var(--text-1)" }}>
              {localizeText(h.verdict_recommendation, lang)}
            </p>
          )}
        </div>
      </section>

      {/* Evidence for / against / missing */}
      <Section title={t("evidence.title")}>
        <div className="grid gap-5 sm:grid-cols-3">
          <EvidenceColumn title={t("evidence.supports")} color="var(--brick)" ids={h.supporting_evidence_ids} empty={t("evidence.noneGathered")} />
          <EvidenceColumn title={t("evidence.innocent")} color="var(--forest)" ids={h.contradicting_evidence_ids} empty={t("evidence.noneFound")} />
          <div>
            <div className="mb-2 text-[10px] tracking-[0.14em] uppercase" style={{ color: "var(--text-2)" }}>
              {t("evidence.stillNeeded")}
            </div>
            {h.missing_evidence.length ? (
              <ul className="flex flex-col gap-1">
                {h.missing_evidence.map((m, i) => (
                  <li key={i} className="text-xs leading-snug" style={{ color: "var(--text-1)" }}>
                    · {localizeText(m, lang)}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs" style={{ color: "var(--text-2)" }}>{t("evidence.nothingOutstanding")}</p>
            )}
          </div>
        </div>
      </Section>

      {/* What the agent checked */}
      <Section title={t("checks.title")}>
        <AgentChecks hypothesis={h} />
      </Section>

      {/* Relationship map (Cognee) — collapsed to keep the focus on the decision */}
      <Section title={t("relmap.title")}>
        <details className="group">
          <summary
            className="cursor-pointer select-none text-xs"
            style={{ color: "var(--text-2)" }}
          >
            {t("relmap.show")}
          </summary>
          <div className="mt-3">
            <InvestigationGraphView />
          </div>
        </details>
      </Section>

      {/* Decision */}
      <div className="rounded-sm border p-5" style={{ borderColor: "var(--hairline-strong)", background: "var(--ink-1)" }}>
        <DecisionBar hypothesis={h} />
      </div>
    </div>
  );
}
