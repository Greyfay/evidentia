import type { EvidenceChainStep } from "@/lib/types";
import EvidenceValue from "./EvidenceValue";
import { formatLocator } from "@/lib/format";

const SOURCE_TYPE_LABEL: Record<string, string> = {
  text_row: "GDPdU row",
  csv_row: "CSV row",
  xlsx_cell: "Cell",
  docx_paragraph: "Paragraph",
  pdf_passage: "PDF passage",
  xml_node: "XML node",
};

export default function EvidenceChain({ steps }: { steps: EvidenceChainStep[] }) {
  return (
    <ol className="relative">
      <div
        className="absolute left-[7px] top-2 bottom-2 w-px"
        style={{ background: "var(--hairline-strong)" }}
        aria-hidden
      />
      {steps.map((step, i) => (
        <li key={i} className="relative pl-8 pb-7 last:pb-0">
          <span
            className="absolute left-0 top-1 w-3.5 h-3.5 rounded-full border-2 flex items-center justify-center"
            style={{ borderColor: "var(--amber)", background: "var(--ink-1)" }}
            aria-hidden
          />
          <div className="text-[13px] mb-2" style={{ color: "var(--text-0)" }}>
            <span className="font-mono text-[10px] mr-2" style={{ color: "var(--text-2)" }}>
              {String(i + 1).padStart(2, "0")}
            </span>
            {step.step}
          </div>
          <div className="flex flex-col gap-1.5">
            {step.evidence.map((ev) => (
              <div
                key={ev.evidence_id}
                className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs border rounded-sm px-3 py-2"
                style={{ borderColor: "var(--hairline)", background: "var(--ink-1)" }}
              >
                <span
                  className="text-[9px] tracking-[0.1em] uppercase px-1.5 py-0.5 rounded-[2px] border shrink-0"
                  style={{ color: "var(--text-2)", borderColor: "var(--hairline-strong)" }}
                >
                  {SOURCE_TYPE_LABEL[ev.source_type] ?? ev.source_type}
                </span>
                <EvidenceValue evidenceId={ev.evidence_id} className="font-mono">
                  {ev.raw_value}
                </EvidenceValue>
                <span className="ml-auto font-mono text-[11px]" style={{ color: "var(--text-2)" }}>
                  {ev.source_path} · {formatLocator(ev.locator)}
                </span>
              </div>
            ))}
          </div>
        </li>
      ))}
    </ol>
  );
}
