import type { Engagement } from "@/lib/types";
import { formatDate } from "@/lib/format";

function Stat({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="font-mono mono-num text-2xl leading-none" style={{ color: color ?? "var(--text-0)" }}>
        {value}
      </span>
      <span className="text-[10px] tracking-[0.12em] uppercase" style={{ color: "var(--text-2)" }}>
        {label}
      </span>
    </div>
  );
}

export default function EngagementHeader({ engagement }: { engagement: Engagement }) {
  const { counts } = engagement;
  return (
    <header
      className="border-b pb-6 mb-8"
      style={{ borderColor: "var(--hairline)" }}
    >
      <div className="flex items-center gap-2 text-[10px] tracking-[0.2em] uppercase mb-3" style={{ color: "var(--amber)" }}>
        <span className="w-1.5 h-1.5 rounded-full" style={{ background: "var(--amber)" }} />
        Compiled engagement
      </div>
      <div className="flex flex-wrap items-end justify-between gap-6">
        <div>
          <h1
            className="text-[28px] sm:text-[34px] leading-tight"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-0)" }}
          >
            {engagement.name}
          </h1>
          <p className="mt-2 text-xs font-mono" style={{ color: "var(--text-2)" }}>
            {engagement.dossier_root} · methodology {engagement.methodology_version} · compiled{" "}
            {formatDate(engagement.compiled_at)}
          </p>
        </div>
      </div>

      <div className="mt-6 grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-x-6 gap-y-5">
        <Stat label="Source files" value={counts.source_files} />
        <Stat label="Evidence records" value={counts.evidence_records} />
        <Stat label="Entities" value={counts.entities} />
        <Stat label="Events" value={counts.events} />
        <Stat label="Confirmed" value={counts.confirmed} color="var(--brick)" />
        <Stat label="Human review" value={counts.human_review} color="var(--steel)" />
        <Stat label="Dismissed" value={counts.dismissed} color="var(--forest)" />
        <Stat label="Rejected" value={counts.rejected} color="var(--slate)" />
      </div>
    </header>
  );
}
