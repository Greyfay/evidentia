"use client";

import { useCallback, useId, useState } from "react";
import { useInvestigation } from "@/lib/investigation-context";
import { useLang } from "@/lib/i18n";
import { formatBytes } from "@/lib/format";

export default function UploadZone() {
  const { engagement, uploading, uploadDossier, starting, startInvestigation, investigation } =
    useInvestigation();
  const { t } = useLang();
  const [dragging, setDragging] = useState(false);
  // Until the auditor edits it, the objective tracks the language's sample text.
  const [editedObjective, setEditedObjective] = useState<string | null>(null);
  const objective = editedObjective ?? t("upload.objectiveDefault");
  const inputId = useId();

  const handleFiles = useCallback(
    (files: FileList | null) => {
      if (!files || files.length === 0) return;
      void uploadDossier(Array.from(files));
    },
    [uploadDossier],
  );

  // --- Once the investigation is running, the dossier collapses to a slim strip ---
  if (investigation && engagement) {
    return (
      <section className="mb-6 flex flex-wrap items-center gap-x-5 gap-y-1.5 border rounded-sm px-4 py-2.5"
        style={{ borderColor: "var(--hairline)", background: "var(--ink-1)" }}>
        <span className="text-[13px]" style={{ fontFamily: "var(--font-display)", color: "var(--text-0)" }}>
          {engagement.name}
        </span>
        <span className="text-[11px]" style={{ color: "var(--text-2)" }}>
          {engagement.counts.source_files} {t("upload.sourceFiles").toLowerCase()} ·{" "}
          {engagement.counts.evidence_records} {t("upload.evidence").toLowerCase()} ·{" "}
          {engagement.counts.entities} {t("upload.entities").toLowerCase()}
        </span>
      </section>
    );
  }

  // --- Dossier uploaded, waiting for an objective to begin ---
  if (engagement) {
    return (
      <section className="mb-8">
        <div className="border rounded-sm p-5" style={{ borderColor: "var(--hairline)", background: "var(--ink-1)" }}>
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <h3 className="text-[16px]" style={{ fontFamily: "var(--font-display)", color: "var(--text-0)" }}>
              {engagement.name}
            </h3>
            <span className="text-[11px]" style={{ color: "var(--forest)" }}>
              {t("upload.ready")}
            </span>
          </div>
          <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Stat label={t("upload.sourceFiles")} value={engagement.counts.source_files} />
            <Stat label={t("upload.evidence")} value={engagement.counts.evidence_records} />
            <Stat label={t("upload.entities")} value={engagement.counts.entities} />
            <Stat label={t("upload.events")} value={engagement.counts.events} />
          </div>
          {engagement.source_files.length > 0 && (
            <ul className="mt-3 flex flex-col gap-1">
              {engagement.source_files.map((f) => (
                <li key={f.path} className="flex items-center justify-between text-[11px]" style={{ color: "var(--text-2)" }}>
                  <span className="truncate font-mono">{f.path}</span>
                  <span className="mono-num shrink-0 pl-3">{formatBytes(f.bytes)}</span>
                </li>
              ))}
            </ul>
          )}

          <div className="mt-5 pt-4 border-t flex flex-col gap-2.5" style={{ borderColor: "var(--hairline)" }}>
            <label htmlFor="objective" className="text-[10px] tracking-[0.14em] uppercase" style={{ color: "var(--text-2)" }}>
              {t("upload.objective")}
            </label>
            <textarea
              id="objective"
              value={objective}
              onChange={(e) => setEditedObjective(e.target.value)}
              rows={2}
              className="w-full resize-none rounded-sm border px-3 py-2 text-sm outline-none"
              style={{ background: "var(--ink-2)", borderColor: "var(--hairline-strong)", color: "var(--text-0)" }}
            />
            <button
              onClick={() => void startInvestigation(objective)}
              disabled={starting || !objective.trim()}
              className="self-start rounded-sm border px-4 py-2 text-xs font-semibold tracking-[0.08em] uppercase transition-colors disabled:opacity-50"
              style={{ borderColor: "var(--amber)", color: "var(--amber)", background: "var(--amber-glow)" }}
            >
              {starting ? t("upload.beginning") : t("upload.begin")}
            </button>
          </div>
        </div>
      </section>
    );
  }

  // --- No dossier yet: the upload dropzone ---
  return (
    <section className="mb-8">
      <label
        htmlFor={inputId}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          handleFiles(e.dataTransfer.files);
        }}
        className="flex cursor-pointer flex-col items-center gap-2 border border-dashed rounded-sm px-6 py-14 text-center transition-colors"
        style={{
          borderColor: dragging ? "var(--amber)" : "var(--hairline-strong)",
          background: dragging ? "var(--amber-glow)" : "var(--ink-1)",
        }}
      >
        <input
          id={inputId}
          type="file"
          multiple
          accept=".zip,.pdf,.xlsx,.xls,.csv,.docx,.xml,.txt"
          className="sr-only"
          onChange={(e) => handleFiles(e.target.files)}
        />
        <span className="text-[15px]" style={{ fontFamily: "var(--font-display)", color: "var(--text-0)" }}>
          {uploading ? t("upload.compiling") : t("upload.dropTitle")}
        </span>
        <span className="text-xs max-w-md leading-relaxed" style={{ color: "var(--text-2)" }}>
          {uploading ? t("upload.compilingHint") : t("upload.dropHint")}
        </span>
      </label>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="mono-num text-lg" style={{ color: "var(--text-0)" }}>
        {value}
      </div>
      <div className="text-[9px] tracking-[0.1em] uppercase" style={{ color: "var(--text-2)" }}>
        {label}
      </div>
    </div>
  );
}
