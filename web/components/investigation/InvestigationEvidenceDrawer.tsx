"use client";

import { useEffect } from "react";
import { useInvestigation } from "@/lib/investigation-context";
import { formatLocator, shortHash } from "@/lib/format";

const SOURCE_TYPE_LABEL: Record<string, string> = {
  text_row: "GDPdU text row",
  csv_row: "CSV row",
  xlsx_cell: "Spreadsheet cell",
  docx_paragraph: "Document paragraph",
  pdf_passage: "PDF passage",
  xml_node: "XML node",
};

export default function InvestigationEvidenceDrawer() {
  const { activeEvidenceId, resolveEvidence, closeEvidence } = useInvestigation();
  const open = activeEvidenceId !== null;
  const hit = activeEvidenceId ? resolveEvidence(activeEvidenceId) : undefined;

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeEvidence();
    };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, closeEvidence]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        aria-label="Close evidence viewer"
        onClick={closeEvidence}
        className="absolute inset-0 bg-black/70 backdrop-blur-[1px]"
        style={{ animation: "fade-in 160ms ease-out" }}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Evidence viewer"
        className="relative h-full w-full max-w-md flex flex-col border-l shadow-2xl"
        style={{ background: "var(--ink-1)", borderColor: "var(--hairline-strong)", animation: "drawer-in 200ms cubic-bezier(0.16,1,0.3,1)" }}
      >
        <div className="exhibit-tag px-5 pt-4 pb-5 border-b" style={{ background: "var(--ink-2)", borderColor: "var(--hairline)" }}>
          <div className="flex items-center justify-between">
            <span className="text-[10px] tracking-[0.18em] uppercase" style={{ color: "var(--amber)" }}>
              Exhibit · Evidence record
            </span>
            <button onClick={closeEvidence} aria-label="Close" className="text-text-2 hover:text-text-0 transition-colors text-lg leading-none px-1">
              ×
            </button>
          </div>
          <div className="mt-2 font-mono text-xs" style={{ color: "var(--text-2)" }}>
            evidence_id <span style={{ color: "var(--text-0)" }}>{activeEvidenceId}</span>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-5">
          {!hit ? (
            <div className="mt-8 text-center">
              <p className="text-sm" style={{ color: "var(--text-1)" }}>
                No cached record for evidence_id{" "}
                <span className="font-mono" style={{ color: "var(--text-0)" }}>{activeEvidenceId}</span>.
              </p>
              <p className="mt-2 text-xs" style={{ color: "var(--text-2)" }}>
                The investigation API returns the id only — fetch the full record from the engagement
                dossier to inspect it.
              </p>
            </div>
          ) : (
            <div className="flex flex-col gap-5">
              <div>
                <div className="text-[10px] tracking-[0.14em] uppercase mb-1.5" style={{ color: "var(--text-2)" }}>
                  Raw value
                </div>
                <div
                  className="font-mono text-sm px-3.5 py-3 border rounded-sm whitespace-pre-wrap break-words"
                  style={{ background: "var(--amber-glow)", borderColor: "var(--amber-dim)", color: "var(--text-0)" }}
                >
                  {hit.raw_value}
                </div>
              </div>

              <dl className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-2.5 text-xs">
                <dt style={{ color: "var(--text-2)" }}>Source path</dt>
                <dd className="font-mono break-all" style={{ color: "var(--text-0)" }}>{hit.source_path}</dd>

                <dt style={{ color: "var(--text-2)" }}>Source type</dt>
                <dd style={{ color: "var(--text-0)" }}>{SOURCE_TYPE_LABEL[hit.source_type] ?? hit.source_type}</dd>

                <dt style={{ color: "var(--text-2)" }}>Locator</dt>
                <dd className="font-mono" style={{ color: "var(--text-0)" }}>{formatLocator(hit.locator)}</dd>

                <dt style={{ color: "var(--text-2)" }}>File SHA-256</dt>
                <dd className="font-mono break-all" style={{ color: "var(--text-1)" }} title={hit.file_sha256}>
                  {shortHash(hit.file_sha256)}
                </dd>
              </dl>
            </div>
          )}
        </div>

        <div className="px-5 py-3 border-t text-[10px]" style={{ borderColor: "var(--hairline)", color: "var(--text-2)" }}>
          Chain of custody verified against file hash at compile time.
        </div>
      </div>
    </div>
  );
}
