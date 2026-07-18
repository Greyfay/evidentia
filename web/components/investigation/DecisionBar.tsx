"use client";

import { useState } from "react";
import { useInvestigation } from "@/lib/investigation-context";
import { useLang, localizeText } from "@/lib/i18n";
import EvidenceBadge from "./EvidenceBadge";
import type { Hypothesis } from "@/lib/investigation-types";
import type { HypothesisAction } from "@/lib/investigation-api";

const DECISIONS: { action: HypothesisAction; labelKey: string; hintKey: string; color: string }[] = [
  { action: "submit", labelKey: "decision.confirm", hintKey: "decision.confirmHint", color: "var(--brick)" },
  { action: "dismiss", labelKey: "decision.dismiss", hintKey: "decision.dismissHint", color: "var(--forest)" },
  { action: "challenge", labelKey: "decision.challenge", hintKey: "decision.challengeHint", color: "var(--steel)" },
  { action: "continue", labelKey: "decision.continue", hintKey: "decision.continueHint", color: "var(--text-1)" },
];

export default function DecisionBar({ hypothesis }: { hypothesis: Hypothesis }) {
  const { investigation, actOnHypothesis, sendMessage } = useInvestigation();
  const { t, lang } = useLang();
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);

  // Grounded Q&A thread from the timeline — the agent's answers with any cited
  // evidence made clickable through to the source viewer.
  const thread = (investigation?.timeline ?? []).filter(
    (e) => e.kind === "auditor_message" || e.kind === "assistant_reply",
  );

  const submit = async (text: string) => {
    if (!text.trim()) return;
    setSending(true);
    try {
      await sendMessage(text);
      setMessage("");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="mb-2 text-[10px] tracking-[0.14em] uppercase" style={{ color: "var(--text-2)" }}>
          {t("decision.title")}
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {DECISIONS.map((d) => (
            <button
              key={d.action}
              onClick={() => actOnHypothesis(hypothesis.hypothesis_id, d.action)}
              className="flex flex-col gap-0.5 rounded-sm border px-3 py-2.5 text-left transition-colors hover:bg-[var(--ink-2)]"
              style={{ borderColor: d.color }}
            >
              <span className="text-[12.5px] font-semibold" style={{ color: d.color }}>
                {t(d.labelKey)}
              </span>
              <span className="text-[10px] leading-tight" style={{ color: "var(--text-2)" }}>
                {t(d.hintKey)}
              </span>
            </button>
          ))}
        </div>
      </div>

      {thread.length > 0 && (
        <div className="flex flex-col gap-2">
          <div className="text-[10px] tracking-[0.14em] uppercase" style={{ color: "var(--text-2)" }}>
            {t("decision.conversation")}
          </div>
          {thread.map((e, i) => {
            const agent = e.kind === "assistant_reply";
            return (
              <div key={i} className="rounded-sm border px-3 py-2" style={{ borderColor: "var(--hairline)", background: agent ? "var(--ink-2)" : "var(--ink-1)" }}>
                <div className="text-[9px] tracking-[0.1em] uppercase" style={{ color: agent ? "var(--forest)" : "var(--steel)" }}>
                  {agent ? t("who.agent") : t("who.auditor")}
                </div>
                <p className="mt-1 text-[12.5px] leading-snug" style={{ color: "var(--text-1)" }}>
                  {localizeText(e.detail, lang)}
                </p>
                {agent && e.evidence_ids && e.evidence_ids.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {e.evidence_ids.map((id) => (
                      <EvidenceBadge key={id} evidenceId={id} />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <div>
        <div className="mb-2 flex flex-wrap gap-2">
          {[t("prompt.why"), t("prompt.missing")].map((p) => (
            <button
              key={p}
              onClick={() => void submit(p)}
              disabled={sending}
              className="rounded-full border px-3 py-1 text-[11px] transition-colors disabled:opacity-50"
              style={{ borderColor: "var(--hairline-strong)", color: "var(--text-2)", background: "var(--ink-2)" }}
            >
              {p}
            </button>
          ))}
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit(message);
          }}
          className="flex gap-2"
        >
          <input
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder={t("decision.placeholder")}
            aria-label={t("decision.placeholder")}
            className="flex-1 rounded-sm border px-3 py-2 text-sm outline-none"
            style={{ background: "var(--ink-2)", borderColor: "var(--hairline-strong)", color: "var(--text-0)" }}
          />
          <button
            type="submit"
            disabled={sending || !message.trim()}
            className="rounded-sm border px-4 py-2 text-xs font-semibold tracking-[0.08em] uppercase transition-colors disabled:opacity-40"
            style={{ borderColor: "var(--amber)", color: "var(--amber)", background: "var(--amber-glow)" }}
          >
            {t("decision.send")}
          </button>
        </form>
      </div>
    </div>
  );
}
