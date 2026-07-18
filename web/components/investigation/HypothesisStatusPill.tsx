"use client";

import type { HypothesisStatus } from "@/lib/investigation-types";
import { HYPOTHESIS_STATUS_META } from "@/lib/format";
import { useLang } from "@/lib/i18n";

export default function HypothesisStatusPill({
  status,
  className = "",
}: {
  status: HypothesisStatus;
  className?: string;
}) {
  const meta = HYPOTHESIS_STATUS_META[status];
  const { t } = useLang();
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-[3px] border px-2.5 py-1 text-[10px] font-semibold tracking-[0.1em] uppercase whitespace-nowrap ${className}`}
      style={{ color: meta.color, borderColor: meta.border, background: meta.glow }}
    >
      <span
        className="w-1.5 h-1.5 rounded-full"
        style={{ background: meta.color, animation: status === "active" ? "pulse-dot 1.4s ease-in-out infinite" : undefined }}
      />
      {t(`status.${status}`)}
    </span>
  );
}
