import type { Calculation } from "@/lib/types";
import EvidenceValue from "./EvidenceValue";

export default function CalculationBlock({ calc }: { calc: Calculation }) {
  return (
    <div className="border rounded-sm" style={{ borderColor: "var(--hairline)" }}>
      <div className="px-4 py-3 border-b flex items-center justify-between flex-wrap gap-2" style={{ borderColor: "var(--hairline)" }}>
        <span className="font-mono text-sm" style={{ color: "var(--text-0)" }}>
          {calc.expression}
        </span>
        <span className="font-mono mono-num text-lg" style={{ color: "var(--amber)" }}>
          = {calc.result}
        </span>
      </div>

      {calc.inputs.length > 0 && (
        <div className="px-4 py-3 flex flex-col gap-1.5 border-b" style={{ borderColor: "var(--hairline)" }}>
          {calc.inputs.map((input, i) => (
            <div key={i} className="flex items-center justify-between text-xs gap-3">
              <span style={{ color: "var(--text-2)" }}>{input.label}</span>
              <EvidenceValue evidenceId={input.evidence_id} className="font-mono mono-num" title={`Source for ${input.label}`}>
                {input.value}
              </EvidenceValue>
            </div>
          ))}
        </div>
      )}

      <div className="px-4 py-3">
        <div className="text-[9px] tracking-[0.14em] uppercase mb-1.5" style={{ color: "var(--text-2)" }}>
          Deterministic query
        </div>
        <pre
          className="font-mono text-[12px] leading-relaxed overflow-x-auto whitespace-pre-wrap break-words p-3 rounded-sm border"
          style={{ background: "var(--ink-2)", borderColor: "var(--hairline)", color: "var(--text-1)" }}
        >
          {calc.sql}
        </pre>
      </div>
    </div>
  );
}
