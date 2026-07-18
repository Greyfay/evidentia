"use client";

import { useEffect, useRef, useState } from "react";
import { useLang } from "@/lib/i18n";
import type { EvidenceLocator } from "@/lib/investigation-types";

/** Inline preview of the exact original file an evidence id came from.
 *
 * The viewer is chosen by the file extension of ``sourcePath``: PDFs render in an
 * <iframe> (jumping to the cited page), plain-text/CSV is fetched and shown with the
 * cited row highlighted, and anything else (xlsx/docx/…) falls back to a download link.
 * Any load failure degrades to the same download link — the original is always reachable. */
export default function SourceFilePreview({
  url,
  sourcePath,
  locator,
}: {
  url: string;
  sourcePath: string;
  locator?: EvidenceLocator | null;
}) {
  const { t } = useLang();
  const ext = extensionOf(sourcePath);

  if (ext === "pdf") {
    const src = locator?.page ? `${url}#page=${locator.page}` : url;
    return (
      <Frame>
        <iframe
          src={src}
          title={sourcePath}
          className="w-full"
          style={{ height: 420, border: "none", background: "var(--ink-2)" }}
        />
        <OpenLink url={url} label={t("sourceFile.open")} />
      </Frame>
    );
  }

  if (ext === "csv" || ext === "txt") {
    return <TextPreview url={url} highlightLine={locator?.row ?? null} />;
  }

  return (
    <Frame>
      <p className="text-xs" style={{ color: "var(--text-2)" }}>
        {t("sourceFile.unavailable")}
      </p>
      <DownloadLink url={url} label={t("sourceFile.download")} />
    </Frame>
  );
}

function TextPreview({ url, highlightLine }: { url: string; highlightLine: number | null }) {
  const { t } = useLang();
  const [text, setText] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const highlightRef = useRef<HTMLSpanElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    setText(null);
    setFailed(false);
    fetch(url, { cache: "no-store" })
      .then((res) => {
        if (!res.ok) throw new Error(`status ${res.status}`);
        return res.text();
      })
      .then((body) => {
        if (!cancelled) setText(body);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [url]);

  useEffect(() => {
    highlightRef.current?.scrollIntoView({ block: "center" });
  }, [text]);

  if (failed) {
    return (
      <Frame>
        <p className="text-xs" style={{ color: "var(--brick)" }}>
          {t("sourceFile.error")}
        </p>
        <DownloadLink url={url} label={t("sourceFile.download")} />
      </Frame>
    );
  }

  if (text === null) {
    return (
      <Frame>
        <p className="text-xs" style={{ color: "var(--text-2)" }}>
          {t("sourceFile.loading")}
        </p>
      </Frame>
    );
  }

  const lines = text.split("\n");
  return (
    <Frame>
      <pre
        className="max-h-[420px] overflow-auto font-mono text-[11px] leading-[1.6] whitespace-pre"
        style={{ color: "var(--text-1)" }}
      >
        {lines.map((line, i) => {
          const lineNo = i + 1;
          const isHit = highlightLine === lineNo;
          return (
            <span
              key={i}
              ref={isHit ? highlightRef : undefined}
              className="block px-2"
              style={
                isHit
                  ? { background: "var(--amber-glow)", color: "var(--text-0)" }
                  : undefined
              }
            >
              <span className="mr-3 inline-block w-8 select-none text-right" style={{ color: "var(--text-2)" }}>
                {lineNo}
              </span>
              {line || " "}
            </span>
          );
        })}
      </pre>
      <OpenLink url={url} label={t("sourceFile.open")} />
    </Frame>
  );
}

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="flex flex-col gap-2 rounded-sm border p-2.5"
      style={{ borderColor: "var(--hairline)", background: "var(--ink-2)" }}
    >
      {children}
    </div>
  );
}

function OpenLink({ url, label }: { url: string; label: string }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="self-start text-[11px] underline underline-offset-2"
      style={{ color: "var(--amber)" }}
    >
      {label} ↗
    </a>
  );
}

function DownloadLink({ url, label }: { url: string; label: string }) {
  return (
    <a
      href={url}
      download
      className="self-start text-[11px] underline underline-offset-2"
      style={{ color: "var(--amber)" }}
    >
      {label} ↓
    </a>
  );
}

function extensionOf(path: string): string {
  const clean = path.split(/[?#]/)[0];
  const dot = clean.lastIndexOf(".");
  return dot === -1 ? "" : clean.slice(dot + 1).toLowerCase();
}
