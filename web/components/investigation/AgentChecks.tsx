"use client";

import { useState } from "react";
import { useInvestigation } from "@/lib/investigation-context";
import { humanizeKey } from "@/lib/format";
import { useLang, localizeText, type Lang } from "@/lib/i18n";
import type { CompletedAction, Hypothesis } from "@/lib/investigation-types";
import EvidenceBadge from "./EvidenceBadge";

const KNOWN_TOOLS = new Set([
  "search_dossier",
  "cross_reference_hr_registry",
  "compute_exposure",
  "find_related_entities",
]);

interface Relationship {
  provider: string | null;
  nodeCount: number;
  edgeCount: number;
  enrichment: string | null;
}

interface Fact {
  label: string;
  value: string;
}

// structured_result is a raw tool dict (or a string). Render it as a short
// summary + clean key/value facts — never as JSON, never chain-of-thought.
// Bilingual backend values are resolved to the selected language.
function describeResult(result: CompletedAction["structured_result"], lang: Lang): {
  summary: string | null;
  facts: Fact[];
  relationship: Relationship | null;
} {
  if (result == null) return { summary: null, facts: [], relationship: null };
  if (typeof result === "string") return { summary: result, facts: [], relationship: null };
  if (typeof result !== "object") return { summary: String(result), facts: [], relationship: null };

  const obj = result as Record<string, unknown>;

  // Cognee-style relationship payload → surface as a relationship, not facts.
  if (Array.isArray(obj.nodes) || Array.isArray(obj.edges)) {
    const enrichment = obj.cloud_enrichment ? localizeText(obj.cloud_enrichment, lang) || null : null;
    return {
      summary: obj.summary ? localizeText(obj.summary, lang) || null : null,
      facts: [],
      relationship: {
        provider: typeof obj.provider === "string" ? obj.provider : null,
        nodeCount: Array.isArray(obj.nodes) ? obj.nodes.length : 0,
        edgeCount: Array.isArray(obj.edges) ? obj.edges.length : 0,
        enrichment,
      },
    };
  }

  const scalar = (v: unknown): string | null => {
    if (v == null) return null;
    if (Array.isArray(v)) return v.length ? `${v.length} item${v.length === 1 ? "" : "s"}` : null;
    if (typeof v === "object") {
      const o = v as Record<string, unknown>;
      // Bilingual object → localized text; otherwise a short label field.
      if ("en" in o || "de" in o || "text" in o || "value" in o) return localizeText(o, lang) || null;
      const label = o.detail ?? o.title ?? o.subject ?? o.assertion;
      return typeof label === "string" ? label : null;
    }
    return String(v);
  };

  const summaryKey = ["summary", "detail", "finding", "message"].find(
    (k) => typeof obj[k] === "string" || (obj[k] != null && typeof obj[k] === "object"),
  );
  const summary = summaryKey ? scalar(obj[summaryKey]) : null;

  const facts: Fact[] = [];
  for (const [key, raw] of Object.entries(obj)) {
    if (key === summaryKey) continue;
    const value = scalar(raw);
    if (value != null) facts.push({ label: humanizeKey(key), value });
  }
  return { summary, facts, relationship: null };
}

export default function AgentChecks({ hypothesis }: { hypothesis: Hypothesis }) {
  const { investigation } = useInvestigation();
  const { t } = useLang();
  const completedActions = investigation?.completed_actions ?? [];

  const focusIds = new Set([...hypothesis.supporting_evidence_ids, ...hypothesis.contradicting_evidence_ids]);
  const checks = completedActions.filter((a) => a.evidence_ids.some((id) => focusIds.has(id)));

  if (checks.length === 0) {
    return (
      <p className="text-xs" style={{ color: "var(--text-2)" }}>
        {t("checks.none")}
      </p>
    );
  }

  return (
    <ol className="flex flex-col gap-2">
      {checks.map((a, i) => (
        <CheckRow key={`${a.tool_name}-${i}`} action={a} index={i} />
      ))}
    </ol>
  );
}

function CheckRow({ action, index }: { action: CompletedAction; index: number }) {
  const [open, setOpen] = useState(index === 0);
  const { t, lang } = useLang();
  const toolLabel = KNOWN_TOOLS.has(action.tool_name) ? t(`tool.${action.tool_name}`) : humanizeKey(action.tool_name);
  const { summary, facts, relationship } = describeResult(action.structured_result, lang);
  const hasDetail = facts.length > 0 || !!relationship || !!action.calculation || action.evidence_ids.length > 0 || action.errors.length > 0;
  const failed = action.errors.length > 0;

  return (
    <li className="border rounded-sm" style={{ borderColor: "var(--hairline)", background: "var(--ink-1)" }}>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-start gap-2.5 px-3.5 py-2.5 text-left"
        disabled={!hasDetail}
      >
        <span
          className="mt-[3px] h-1.5 w-1.5 shrink-0 rounded-full"
          style={{ background: failed ? "var(--brick)" : "var(--forest)" }}
          aria-hidden
        />
        <span className="min-w-0 flex-1">
          <span className="block text-[12.5px] font-semibold" style={{ color: "var(--text-0)" }}>
            {toolLabel}
          </span>
          {summary && (
            <span className="mt-0.5 block text-[12px] leading-snug" style={{ color: "var(--text-1)" }}>
              {summary}
            </span>
          )}
        </span>
        {hasDetail && (
          <span className="mt-0.5 shrink-0 text-[10px]" style={{ color: "var(--text-2)" }} aria-hidden>
            {open ? "–" : "+"}
          </span>
        )}
      </button>

      {open && hasDetail && (
        <div className="flex flex-col gap-3 border-t px-3.5 py-3" style={{ borderColor: "var(--hairline)" }}>
          {facts.length > 0 && (
            <dl className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-1.5 text-[11.5px]">
              {facts.map((f) => (
                <div key={f.label} className="contents">
                  <dt style={{ color: "var(--text-2)" }}>{f.label}</dt>
                  <dd style={{ color: "var(--text-0)" }}>{f.value}</dd>
                </div>
              ))}
            </dl>
          )}

          {relationship && (
            <div className="text-[11.5px]" style={{ color: "var(--text-1)" }}>
              {relationship.nodeCount} entities and {relationship.edgeCount} links
              {relationship.provider ? ` via ${relationship.provider}` : ""}.
              {relationship.enrichment ? ` ${relationship.enrichment}.` : ""}
              <span className="mt-1 block text-[10.5px]" style={{ color: "var(--text-2)" }}>
                {t("checks.relationshipTail")}
              </span>
            </div>
          )}

          {action.calculation && (
            <div className="rounded-sm border px-3 py-2" style={{ borderColor: "var(--hairline)", background: "var(--ink-2)" }}>
              <div className="text-[9px] tracking-[0.12em] uppercase" style={{ color: "var(--text-2)" }}>
                {t("checks.calculation")}
              </div>
              <div className="mt-1 font-mono text-[11px] leading-relaxed" style={{ color: "var(--text-1)" }}>
                {action.calculation.expression} ={" "}
                <span style={{ color: "var(--text-0)" }}>{action.calculation.result}</span>
              </div>
            </div>
          )}

          {action.evidence_ids.length > 0 && (
            <div>
              <div className="mb-1.5 text-[9px] tracking-[0.12em] uppercase" style={{ color: "var(--text-2)" }}>
                {t("checks.tracesTo")}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {action.evidence_ids.map((id) => (
                  <EvidenceBadge key={id} evidenceId={id} />
                ))}
              </div>
            </div>
          )}

          {action.errors.length > 0 && (
            <div className="text-[11px]" style={{ color: "var(--brick)" }}>
              {t("checks.couldNotComplete")}: {action.errors.join("; ")}
            </div>
          )}
        </div>
      )}
    </li>
  );
}
