import Link from "next/link";

export default function AppHeader() {
  return (
    <div
      className="border-b"
      style={{ borderColor: "var(--hairline)", background: "var(--ink-0)" }}
    >
      <div className="mx-auto w-full max-w-6xl px-5 sm:px-8 py-3 flex flex-wrap items-center justify-between gap-x-6 gap-y-1">
        <Link href="/" className="flex items-baseline gap-2.5 shrink-0">
          <span
            className="text-[15px] tracking-[0.02em]"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-0)" }}
          >
            Evidentia
          </span>
          <span
            className="w-1 h-1 rounded-full"
            style={{ background: "var(--amber)" }}
            aria-hidden
          />
        </Link>
        <p
          className="text-[10.5px] tracking-[0.04em] font-mono truncate"
          style={{ color: "var(--text-2)" }}
        >
          Models understand. Code verifies. Auditors decide.
        </p>
      </div>
    </div>
  );
}
