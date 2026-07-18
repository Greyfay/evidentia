import type { Verdict, Severity, SourceFileStatus, CounterTestOutcome } from "./types";
import type { HypothesisStatus, HypothesisPriority } from "./investigation-types";

export const VERDICT_META: Record<
  Verdict,
  { label: string; color: string; glow: string; border: string }
> = {
  CONFIRMED: { label: "Confirmed", color: "var(--brick)", glow: "var(--brick-glow)", border: "var(--brick)" },
  HUMAN_REVIEW: { label: "Human review", color: "var(--steel)", glow: "var(--steel-glow)", border: "var(--steel)" },
  DISMISSED: { label: "Dismissed", color: "var(--forest)", glow: "var(--forest-glow)", border: "var(--forest)" },
  REJECTED: { label: "Rejected", color: "var(--slate)", glow: "rgba(107,117,128,0.14)", border: "var(--slate)" },
};

export const SEVERITY_META: Record<Severity, { label: string }> = {
  high: { label: "High" },
  medium: { label: "Medium" },
  low: { label: "Low" },
  control: { label: "Control" },
};

export const STATUS_META: Record<
  SourceFileStatus,
  { label: string; color: string }
> = {
  parsed: { label: "Parsed", color: "var(--forest)" },
  warning: { label: "Warning", color: "var(--amber)" },
  failed: { label: "Failed", color: "var(--brick)" },
  skipped: { label: "Skipped", color: "var(--slate)" },
};

export const COUNTER_TEST_META: Record<
  CounterTestOutcome,
  { label: string; icon: string; color: string }
> = {
  present: { label: "Present", icon: "✓", color: "var(--forest)" },
  absent: { label: "Absent", icon: "✗", color: "var(--brick)" },
  not_applicable: { label: "N/A", icon: "–", color: "var(--slate)" },
};

export const HYPOTHESIS_STATUS_META: Record<
  HypothesisStatus,
  { label: string; color: string; glow: string; border: string }
> = {
  proposed: { label: "Proposed", color: "var(--steel)", glow: "var(--steel-glow)", border: "var(--steel)" },
  active: { label: "Active", color: "var(--amber)", glow: "var(--amber-glow)", border: "var(--amber)" },
  submitted: { label: "Submitted", color: "var(--brick)", glow: "var(--brick-glow)", border: "var(--brick)" },
  dismissed: { label: "Dismissed", color: "var(--forest)", glow: "var(--forest-glow)", border: "var(--forest)" },
  insufficient: { label: "Insufficient", color: "var(--slate)", glow: "rgba(107,117,128,0.14)", border: "var(--slate)" },
  awaiting_auditor: { label: "Awaiting auditor", color: "var(--amber-dim)", glow: "var(--amber-glow)", border: "var(--amber-dim)" },
};

export const HYPOTHESIS_PRIORITY_META: Record<HypothesisPriority, { label: string }> = {
  high: { label: "High" },
  medium: { label: "Medium" },
  low: { label: "Low" },
};

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(1)} ${units[unitIndex]}`;
}

export function formatDate(iso: string): string {
  try {
    return new Intl.DateTimeFormat("en-GB", {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "UTC",
    }).format(new Date(iso)) + " UTC";
  } catch {
    return iso;
  }
}

export function shortHash(hash: string): string {
  if (hash.length <= 12) return hash;
  return `${hash.slice(0, 6)}…${hash.slice(-4)}`;
}

export function formatLocator(locator: {
  row: number | null;
  sheet: string | null;
  cell: string | null;
  page: number | null;
  passage: string | null;
}): string {
  const parts: string[] = [];
  if (locator.sheet) parts.push(`sheet ${locator.sheet}`);
  if (locator.cell) parts.push(`cell ${locator.cell}`);
  if (locator.row !== null && locator.row !== undefined) parts.push(`row ${locator.row}`);
  if (locator.page !== null && locator.page !== undefined) parts.push(`page ${locator.page}`);
  if (locator.passage) parts.push(locator.passage);
  return parts.length ? parts.join(" · ") : "—";
}
