"use client";

import { useState } from "react";
import { useInvestigation } from "@/lib/investigation-context";

const CANNED_PROMPTS = ["Why are you investigating this?", "What evidence is still missing?"];

export default function AuditorPanel() {
  const { investigation, selectedHypothesisId, actOnHypothesis, sendMessage } = useInvestigation();
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);

  const h = investigation?.hypotheses.find((x) => x.hypothesis_id === selectedHypothesisId);
  if (!investigation || !h) return null;

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
    <section className="mb-10">
      <h2 className="text-[11px] tracking-[0.16em] uppercase mb-3" style={{ color: "var(--text-2)" }}>
        5 · Auditor interaction — {h.subject}
      </h2>

      <div className="flex flex-wrap gap-2 mb-3">
        <ActionButton label="Find an innocent explanation" color="var(--steel)" onClick={() => actOnHypothesis(h.hypothesis_id, "challenge")} />
        <ActionButton label="Continue" color="var(--text-1)" onClick={() => actOnHypothesis(h.hypothesis_id, "continue")} />
        <ActionButton label="Submit to admission" color="var(--brick)" onClick={() => actOnHypothesis(h.hypothesis_id, "submit")} />
        <ActionButton label="Dismiss" color="var(--forest)" onClick={() => actOnHypothesis(h.hypothesis_id, "dismiss")} />
      </div>

      <div className="flex flex-wrap gap-2 mb-3">
        {CANNED_PROMPTS.map((p) => (
          <button
            key={p}
            onClick={() => void submit(p)}
            disabled={sending}
            className="rounded-sm border px-3 py-1.5 text-xs transition-colors disabled:opacity-50"
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
          placeholder="Ask the agent a question, or leave an instruction…"
          className="flex-1 rounded-sm border px-3 py-2 text-sm outline-none"
          style={{ background: "var(--ink-2)", borderColor: "var(--hairline-strong)", color: "var(--text-0)" }}
        />
        <button
          type="submit"
          disabled={sending || !message.trim()}
          className="rounded-sm border px-4 py-2 text-xs font-semibold tracking-[0.08em] uppercase transition-colors disabled:opacity-40"
          style={{ borderColor: "var(--amber)", color: "var(--amber)", background: "var(--amber-glow)" }}
        >
          Send
        </button>
      </form>
    </section>
  );
}

function ActionButton({ label, color, onClick }: { label: string; color: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="rounded-sm border px-3.5 py-2 text-xs font-medium transition-colors"
      style={{ borderColor: color, color, background: "transparent" }}
    >
      {label}
    </button>
  );
}
