import type { CounterTest } from "@/lib/types";
import { COUNTER_TEST_META } from "@/lib/format";
import EvidenceValue from "./EvidenceValue";

export default function CounterTestsTable({ tests }: { tests: CounterTest[] }) {
  if (tests.length === 0) {
    return (
      <p className="text-xs" style={{ color: "var(--text-2)" }}>
        No counter-tests recorded for this case.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      {tests.map((t, i) => {
        const meta = COUNTER_TEST_META[t.outcome];
        return (
          <div
            key={i}
            className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 border rounded-sm px-3.5 py-3"
            style={{ borderColor: "var(--hairline)" }}
          >
            <span
              className="row-span-2 self-start flex items-center justify-center w-6 h-6 rounded-full border text-sm font-mono"
              style={{ color: meta.color, borderColor: meta.color }}
              aria-hidden
            >
              {meta.icon}
            </span>
            <div className="flex items-center justify-between gap-3">
              <span className="text-[13px]" style={{ color: "var(--text-0)" }}>
                {t.name.replaceAll("_", " ")}
              </span>
              <span className="text-[10px] tracking-[0.1em] uppercase" style={{ color: meta.color }}>
                {meta.label}
              </span>
            </div>
            <p className="text-xs leading-relaxed" style={{ color: "var(--text-1)" }}>
              {t.detail}
            </p>
            {t.evidence.length > 0 && (
              <div className="col-start-2 flex flex-wrap gap-2 mt-1">
                {t.evidence.map((ev) => (
                  <EvidenceValue key={ev.evidence_id} evidenceId={ev.evidence_id} className="font-mono text-[11px]">
                    {ev.raw_value}
                  </EvidenceValue>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
