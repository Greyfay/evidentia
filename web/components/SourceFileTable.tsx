import type { SourceFile } from "@/lib/types";
import { STATUS_META, shortHash } from "@/lib/format";

const TYPE_LABEL: Record<string, string> = {
  gdpdu: "GDPdU",
  csv: "CSV",
  xlsx: "XLSX",
  docx: "DOCX",
  pdf: "PDF",
};

export default function SourceFileTable({ files }: { files: SourceFile[] }) {
  return (
    <div className="overflow-x-auto border rounded-sm" style={{ borderColor: "var(--hairline)" }}>
      <table className="w-full text-left text-[13px] min-w-[720px]">
        <thead>
          <tr
            className="text-[10px] tracking-[0.12em] uppercase"
            style={{ color: "var(--text-2)", background: "var(--ink-2)" }}
          >
            <th className="px-4 py-2.5 font-medium">Path</th>
            <th className="px-3 py-2.5 font-medium">Type</th>
            <th className="px-3 py-2.5 font-medium">Status</th>
            <th className="px-3 py-2.5 font-medium text-right">Source → parsed</th>
            <th className="px-3 py-2.5 font-medium">Warnings</th>
            <th className="px-4 py-2.5 font-medium">SHA-256</th>
          </tr>
        </thead>
        <tbody>
          {files.map((f) => {
            const status = STATUS_META[f.status];
            const mismatch = f.source_rows !== f.parsed_rows;
            return (
              <tr
                key={f.path}
                className="border-t"
                style={{ borderColor: "var(--hairline)" }}
              >
                <td className="px-4 py-2.5 font-mono text-text-0" style={{ color: "var(--text-0)" }}>
                  {f.path}
                </td>
                <td className="px-3 py-2.5">
                  <span
                    className="text-[10px] font-semibold tracking-[0.08em] uppercase px-1.5 py-0.5 rounded-[2px] border"
                    style={{ color: "var(--text-1)", borderColor: "var(--hairline-strong)" }}
                  >
                    {TYPE_LABEL[f.type] ?? f.type}
                  </span>
                </td>
                <td className="px-3 py-2.5">
                  <span className="inline-flex items-center gap-1.5" style={{ color: status.color }}>
                    <span className="w-1.5 h-1.5 rounded-full" style={{ background: status.color }} />
                    {status.label}
                  </span>
                </td>
                <td
                  className="px-3 py-2.5 text-right font-mono mono-num"
                  style={{ color: mismatch ? "var(--amber)" : "var(--text-1)" }}
                >
                  {f.source_rows} → {f.parsed_rows}
                </td>
                <td className="px-3 py-2.5 text-xs" style={{ color: f.warnings.length ? "var(--amber)" : "var(--text-2)" }}>
                  {f.warnings.length ? f.warnings.join("; ") : "—"}
                </td>
                <td className="px-4 py-2.5 font-mono text-xs" style={{ color: "var(--text-2)" }} title={f.sha256}>
                  {shortHash(f.sha256)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
