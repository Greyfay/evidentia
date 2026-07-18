"use client";

import { useCallback, useRef, useState } from "react";
import { useInvestigation } from "@/lib/investigation-context";
import { formatBytes } from "@/lib/format";

export default function UploadZone() {
  const { engagement, uploading, uploadDossier, starting, startInvestigation, usingFallback, investigation, error } =
    useInvestigation();
  const [dragging, setDragging] = useState(false);
  const [objective, setObjective] = useState(
    "Determine whether Q4 vendor onboarding created undisclosed related-party or segregation-of-duties exposure.",
  );
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    (file: File | undefined) => {
      if (!file) return;
      void uploadDossier(file);
    },
    [uploadDossier],
  );

  return (
    <section className="mb-10">
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-[11px] tracking-[0.16em] uppercase" style={{ color: "var(--text-2)" }}>
          1 · Dossier
        </h2>
        {usingFallback && (
          <span className="text-[10.5px] font-mono" style={{ color: "var(--amber)" }}>
            demo data
          </span>
        )}
      </div>

      {error && (
        <div
          className="mb-3 rounded-sm border px-3 py-2 text-xs"
          style={{ borderColor: "var(--brick)", color: "var(--brick)" }}
        >
          {error}. The bundled demo remains available; check that the API is running on port 8000.
        </div>
      )}

      {!engagement ? (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            handleFile(e.dataTransfer.files[0]);
          }}
          onClick={() => inputRef.current?.click()}
          className="cursor-pointer border border-dashed rounded-sm px-6 py-12 text-center transition-colors"
          style={{
            borderColor: dragging ? "var(--amber)" : "var(--hairline-strong)",
            background: dragging ? "var(--amber-glow)" : "var(--ink-1)",
          }}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".zip"
            className="hidden"
            onChange={(e) => handleFile(e.target.files?.[0])}
          />
          <p className="text-sm" style={{ color: "var(--text-1)" }}>
            {uploading ? "Uploading and compiling dossier…" : "Drop a case dossier .zip, or click to choose one"}
          </p>
          <p className="mt-1.5 text-xs" style={{ color: "var(--text-2)" }}>
            POST /engagements/upload — parsed into evidence records before any hypothesis is proposed.
          </p>
        </div>
      ) : (
        <div className="border rounded-sm p-4" style={{ borderColor: "var(--hairline)", background: "var(--ink-1)" }}>
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <h3 className="text-[15px]" style={{ fontFamily: "var(--font-display)", color: "var(--text-0)" }}>
              {engagement.name}
            </h3>
            <span className="font-mono text-[10.5px]" style={{ color: "var(--text-2)" }}>
              {engagement.engagement_id}
            </span>
          </div>
          <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Stat label="Source files" value={engagement.counts.source_files} />
            <Stat label="Evidence records" value={engagement.counts.evidence_records} />
            <Stat label="Entities" value={engagement.counts.entities} />
            <Stat label="Events" value={engagement.counts.events} />
          </div>
          {engagement.source_files.length > 0 && (
            <ul className="mt-3 flex flex-col gap-1">
              {engagement.source_files.map((f) => (
                <li key={f.path} className="flex items-center justify-between font-mono text-[11px]" style={{ color: "var(--text-2)" }}>
                  <span className="truncate">{f.path}</span>
                  <span>{formatBytes(f.bytes)}</span>
                </li>
              ))}
            </ul>
          )}

          {!investigation && (
            <div className="mt-5 pt-4 border-t flex flex-col gap-2.5" style={{ borderColor: "var(--hairline)" }}>
              <label className="text-[10px] tracking-[0.14em] uppercase" style={{ color: "var(--text-2)" }}>
                Investigation objective
              </label>
              <textarea
                value={objective}
                onChange={(e) => setObjective(e.target.value)}
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
                {starting ? "Starting investigation…" : "Start investigation"}
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="font-mono mono-num text-lg" style={{ color: "var(--text-0)" }}>
        {value}
      </div>
      <div className="text-[9px] tracking-[0.1em] uppercase" style={{ color: "var(--text-2)" }}>
        {label}
      </div>
    </div>
  );
}
