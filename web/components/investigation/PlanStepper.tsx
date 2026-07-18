"use client";

import { useInvestigation } from "@/lib/investigation-context";
import EvidenceBadge from "./EvidenceBadge";

const STATUS_LABEL: Record<string, string> = {
  in_progress: "In progress",
  awaiting_auditor: "Awaiting auditor",
  completed: "Completed",
  stopped: "Stopped",
};

// structured_result is the raw dict a deterministic tool returns; its shape
// varies per tool (flat scalars, or nested vendors/groups arrays). Render it as
// a readable one-liner — never hand React the object itself.
function formatStructuredResult(result: unknown): string {
  if (result == null) return "";
  if (typeof result === "string") return result;
  if (typeof result !== "object") return String(result);
  const entries = Object.entries(result as Record<string, unknown>).filter(
    ([, v]) => v != null && !(Array.isArray(v) && v.length === 0),
  );
  const describe = (v: unknown): string => {
    if (v != null && typeof v === "object") {
      const o = v as Record<string, unknown>;
      const label = o.detail ?? o.title ?? o.subject ?? o.assertion;
      return typeof label === "string" ? label : JSON.stringify(v);
    }
    return String(v);
  };
  return entries
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.map(describe).join("; ") : describe(v)}`)
    .join(" · ");
}

export default function PlanStepper() {
  const { investigation, stepping, runNextStep, runToCompletion } = useInvestigation();
  if (!investigation) return null;

  const done = investigation.status === "completed" || investigation.status === "stopped";

  return (
    <section className="mb-10">
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-3">
        <h2 className="text-[11px] tracking-[0.16em] uppercase" style={{ color: "var(--text-2)" }}>
          4 · Live plan
        </h2>
        <span className="font-mono text-[10.5px] uppercase tracking-[0.08em]" style={{ color: "var(--amber)" }}>
          {STATUS_LABEL[investigation.status] ?? investigation.status}
        </span>
      </div>

      <div className="flex flex-wrap gap-2 mb-4">
        <button
          onClick={() => void runNextStep()}
          disabled={stepping || done}
          className="rounded-sm border px-4 py-2 text-xs font-semibold tracking-[0.08em] uppercase transition-colors disabled:opacity-40"
          style={{ borderColor: "var(--amber)", color: "var(--amber)", background: "var(--amber-glow)" }}
        >
          {stepping ? "Working…" : "Run next step"}
        </button>
        <button
          onClick={() => void runToCompletion()}
          disabled={stepping || done}
          className="rounded-sm border px-4 py-2 text-xs font-semibold tracking-[0.08em] uppercase transition-colors disabled:opacity-40"
          style={{ borderColor: "var(--hairline-strong)", color: "var(--text-1)", background: "var(--ink-2)" }}
        >
          Run to completion
        </button>
      </div>

      {investigation.completed_actions.length === 0 ? (
        <p className="text-xs" style={{ color: "var(--text-2)" }}>No tool calls executed yet.</p>
      ) : (
        <ol className="flex flex-col gap-2">
          {investigation.completed_actions.map((a, i) => (
            <li
              key={i}
              className="flex flex-col gap-1.5 border rounded-sm px-3.5 py-2.5"
              style={{ borderColor: "var(--hairline)", background: "var(--ink-1)" }}
            >
              <div className="flex items-center justify-between gap-3">
                <span className="font-mono text-[11px]" style={{ color: "var(--steel)" }}>
                  {a.tool_name}
                </span>
                <span className="font-mono text-[9.5px]" style={{ color: "var(--text-2)" }}>
                  {new Date(a.timestamp).toLocaleTimeString("en-GB", { timeZone: "UTC", hour: "2-digit", minute: "2-digit", second: "2-digit" })}{" "}
                  UTC
                </span>
              </div>
              {formatStructuredResult(a.structured_result) && (
                <p className="text-[12.5px] leading-snug" style={{ color: "var(--text-1)" }}>
                  {formatStructuredResult(a.structured_result)}
                </p>
              )}
              {a.calculation && (
                <div className="font-mono text-[10.5px]" style={{ color: "var(--text-2)" }}>
                  {a.calculation.expression} = <span style={{ color: "var(--text-0)" }}>{a.calculation.result}</span>
                </div>
              )}
              {a.evidence_ids.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mt-0.5">
                  {a.evidence_ids.map((id) => (
                    <EvidenceBadge key={id} evidenceId={id} />
                  ))}
                </div>
              )}
              {a.errors.length > 0 && (
                <div className="text-[11px]" style={{ color: "var(--brick)" }}>
                  {a.errors.join(" · ")}
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
