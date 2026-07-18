"use client";

import { useEffect } from "react";
import { useInvestigation } from "@/lib/investigation-context";
import { useLang } from "@/lib/i18n";

export default function InvestigationEvidenceDrawer() {
  const { activeEvidenceId, activeEvidence, evidenceLoading, evidenceError, closeEvidence } = useInvestigation();
  const { t } = useLang();
  const open = activeEvidenceId !== null;

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
        aria-label={t("drawer.close")}
        onClick={closeEvidence}
        className="absolute inset-0 bg-black/70 backdrop-blur-[1px]"
        style={{ animation: "fade-in 160ms ease-out" }}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t("drawer.title")}
        className="relative h-full w-full max-w-md flex flex-col border-l shadow-2xl"
        style={{ background: "var(--ink-1)", borderColor: "var(--hairline-strong)", animation: "drawer-in 200ms cubic-bezier(0.16,1,0.3,1)" }}
      >
        <div className="exhibit-tag px-5 pt-4 pb-5 border-b" style={{ background: "var(--ink-2)", borderColor: "var(--hairline)" }}>
          <div className="flex items-center justify-between">
            <span className="text-[10px] tracking-[0.18em] uppercase" style={{ color: "var(--amber)" }}>
              {t("drawer.title")}
            </span>
            <button onClick={closeEvidence} aria-label={t("drawer.close")} className="text-text-2 hover:text-text-0 transition-colors text-lg leading-none px-1">
              ×
            </button>
          </div>
          <div className="mt-2 font-mono text-xs" style={{ color: "var(--text-2)" }}>
            evidence_id <span style={{ color: "var(--text-0)" }}>{activeEvidenceId}</span>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-5">
          {evidenceLoading ? (
            <p className="mt-8 text-center text-sm" style={{ color: "var(--text-2)" }}>
              {t("drawer.loading")}
            </p>
          ) : evidenceError ? (
            <p className="mt-8 text-center text-sm" style={{ color: "var(--brick)" }}>
              {t("drawer.error")}
            </p>
          ) : !activeEvidence ? (
            <p className="mt-8 text-center text-sm" style={{ color: "var(--text-1)" }}>
              {t("drawer.missing")}
            </p>
          ) : (
            <div className="flex flex-col gap-5">
              <div>
                <div className="text-[10px] tracking-[0.14em] uppercase mb-1.5" style={{ color: "var(--text-2)" }}>
                  {t("drawer.snippet")}
                </div>
                <div
                  className="font-mono text-sm px-3.5 py-3 border rounded-sm whitespace-pre-wrap break-words"
                  style={{ background: "var(--amber-glow)", borderColor: "var(--amber-dim)", color: "var(--text-0)" }}
                >
                  {activeEvidence.snippet}
                </div>
              </div>

              <dl className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-2.5 text-xs">
                <dt style={{ color: "var(--text-2)" }}>{t("drawer.source")}</dt>
                <dd className="font-mono break-words" style={{ color: "var(--text-0)" }}>{activeEvidence.source}</dd>

                <dt style={{ color: "var(--text-2)" }}>{t("drawer.kind")}</dt>
                <dd style={{ color: "var(--text-0)" }}>{activeEvidence.kind}</dd>
              </dl>
            </div>
          )}
        </div>

        <div className="px-5 py-3 border-t text-[10px]" style={{ borderColor: "var(--hairline)", color: "var(--text-2)" }}>
          {t("drawer.chain")}
        </div>
      </div>
    </div>
  );
}
