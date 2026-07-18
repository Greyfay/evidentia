"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLang, type Lang } from "@/lib/i18n";

export default function AppHeader() {
  const pathname = usePathname();
  const { t } = useLang();

  return (
    <div
      className="border-b"
      style={{ borderColor: "var(--hairline)", background: "var(--ink-0)" }}
    >
      <div className="mx-auto w-full max-w-6xl px-5 sm:px-8 py-3 flex flex-wrap items-center justify-between gap-x-6 gap-y-1">
        <div className="flex items-center gap-6 shrink-0">
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
          <nav className="flex items-center gap-4 text-[11.5px] tracking-[0.04em]">
            <NavLink href="/" label={t("nav.caseBoard")} active={pathname === "/"} />
            <NavLink href="/investigate" label={t("nav.investigate")} active={pathname?.startsWith("/investigate") ?? false} />
          </nav>
        </div>
        <div className="flex items-center gap-4">
          <p
            className="hidden md:block text-[10.5px] tracking-[0.04em] font-mono truncate"
            style={{ color: "var(--text-2)" }}
          >
            {t("nav.tagline")}
          </p>
          <LanguageToggle />
        </div>
      </div>
    </div>
  );
}

function LanguageToggle() {
  const { lang, setLang, t } = useLang();
  const options: Lang[] = ["en", "de"];
  return (
    <div
      role="group"
      aria-label={t("lang.aria")}
      className="flex items-center overflow-hidden rounded-sm border"
      style={{ borderColor: "var(--hairline-strong)" }}
    >
      {options.map((opt) => {
        const active = lang === opt;
        return (
          <button
            key={opt}
            onClick={() => setLang(opt)}
            aria-pressed={active}
            className="px-2 py-1 text-[10.5px] font-semibold tracking-[0.1em] uppercase transition-colors"
            style={{
              color: active ? "var(--ink-0)" : "var(--text-2)",
              background: active ? "var(--amber)" : "transparent",
            }}
          >
            {opt}
          </button>
        );
      })}
    </div>
  );
}

function NavLink({ href, label, active }: { href: string; label: string; active: boolean }) {
  return (
    <Link
      href={href}
      className="transition-colors"
      style={{ color: active ? "var(--amber)" : "var(--text-2)" }}
    >
      {label}
    </Link>
  );
}
