import type { Severity } from "@/lib/types";
import { SEVERITY_META } from "@/lib/format";

const DOTS: Record<Severity, number> = { high: 3, medium: 2, low: 1, control: 0 };

export default function SeverityTag({ severity }: { severity: Severity }) {
  const meta = SEVERITY_META[severity];
  const dots = DOTS[severity];
  return (
    <span className="inline-flex items-center gap-1.5 text-[10px] tracking-[0.1em] uppercase" style={{ color: "var(--text-2)" }}>
      {severity === "control" ? (
        <svg width="9" height="9" viewBox="0 0 9 9" aria-hidden>
          <rect x="0.5" y="0.5" width="8" height="8" fill="none" stroke="var(--text-2)" strokeWidth="1" />
        </svg>
      ) : (
        <span className="inline-flex gap-[3px]" aria-hidden>
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className="w-[5px] h-[5px] rounded-full"
              style={{ background: i < dots ? "var(--brick)" : "var(--hairline-strong)" }}
            />
          ))}
        </span>
      )}
      {meta.label}
    </span>
  );
}
