"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

export type Lang = "en" | "de";

const STORAGE_KEY = "evidentia-lang";

// Flat UI-chrome dictionary. Only interface labels live here — never source data,
// vendor names, or the agent's narrative (those are localized by picking a
// backend-provided variant, see localizeText).
const STRINGS: Record<Lang, Record<string, string>> = {
  en: {
    "nav.caseBoard": "Case board",
    "nav.investigate": "Investigate",
    "nav.tagline": "Models understand. Code verifies. Auditors decide.",
    "lang.aria": "Interface language",

    "page.title": "Investigation workspace",
    "page.intro":
      "Hand the agent a dossier and an objective. It proposes suspicions, runs forensic checks, tests innocent explanations, and traces every figure to its source — you make the call.",

    "banner.demo":
      "Demo mode — no live agent connected. Showing a sample investigation so you can explore the workspace.",
    "banner.error": "Something went wrong talking to the agent.",
    "action.retry": "Retry",
    "action.dismiss": "Dismiss",
    "error.upload": "The dossier could not be uploaded. Check the file and try again.",
    "error.start": "The investigation could not be started.",
    "error.step": "The agent could not complete that step.",
    "error.decision": "Your decision could not be recorded.",
    "error.message": "Your message could not be sent.",
    "error.generic": "The request to the agent failed.",

    "badge.live": "Live",
    "badge.partial": "Partial",
    "badge.fallback": "Fallback",
    "badge.planner": "planner",

    "upload.dropTitle": "Drop a case dossier, or choose a file",
    "upload.dropHint":
      "A .zip of accounting exports. Every figure is parsed into an evidence record before any suspicion is raised.",
    "upload.compiling": "Compiling dossier…",
    "upload.compilingHint": "Parsing exports into traceable evidence records.",
    "upload.ready": "Compiled — ready to investigate",
    "upload.sourceFiles": "Source files",
    "upload.evidence": "Evidence records",
    "upload.entities": "Entities",
    "upload.events": "Events",
    "upload.objective": "What should the agent investigate?",
    "upload.objectiveDefault":
      "Determine whether Q4 vendor onboarding created undisclosed related-party or segregation-of-duties exposure.",
    "upload.begin": "Begin investigation",
    "upload.beginning": "Opening investigation…",

    "toolbar.in_progress": "In progress",
    "toolbar.awaiting_auditor": "Awaiting your decision",
    "toolbar.completed": "Completed",
    "toolbar.stopped": "Stopped",
    "toolbar.advance": "Advance one step",
    "toolbar.working": "Working…",
    "toolbar.runToEnd": "Run to end",

    "docket.title": "Lines of inquiry",
    "docket.startHere": "Start here",
    "docket.priority": "{p} priority",
    "priority.high": "high",
    "priority.medium": "medium",
    "priority.low": "low",

    "status.proposed": "Proposed",
    "status.active": "Active",
    "status.submitted": "Submitted",
    "status.dismissed": "Dismissed",
    "status.insufficient": "Insufficient",
    "status.awaiting_auditor": "Awaiting auditor",

    "verdict.proposed": "Not yet examined",
    "verdict.active": "Under examination",
    "verdict.submitted": "Recommends confirming",
    "verdict.dismissed": "Recommends dismissing",
    "verdict.insufficient": "Evidence insufficient",
    "verdict.awaiting_auditor": "Needs your decision",

    "file.chooseInquiry": "Choose a line of inquiry to open its file.",
    "file.amountAtRisk": "Amount at risk",
    "file.notComputed": "Not yet computed",

    "evidence.title": "Evidence",
    "evidence.supports": "Supports the suspicion",
    "evidence.innocent": "Innocent explanations",
    "evidence.stillNeeded": "Still needed",
    "evidence.noneGathered": "None gathered yet.",
    "evidence.noneFound": "None found — nothing exonerates it yet.",
    "evidence.nothingOutstanding": "Nothing outstanding.",

    "tool.search_dossier": "Searched the dossier",
    "tool.cross_reference_hr_registry": "Cross-referenced the HR registry",
    "tool.compute_exposure": "Computed the exposure",
    "tool.find_related_entities": "Mapped related entities",
    "checks.title": "What the agent checked",
    "checks.none": "The agent has not run any checks on this line of inquiry yet. Advance a step to begin.",
    "checks.calculation": "Calculation",
    "checks.tracesTo": "Traces to",
    "checks.couldNotComplete": "Could not complete",
    "checks.relationshipTail": "Shown in the relationship map below.",

    "relmap.title": "Relationship map",
    "relmap.show": "Show how the entities connect",
    "relmap.none": "No relationship data available yet.",

    "decision.title": "Your decision",
    "decision.confirm": "Confirm finding",
    "decision.confirmHint": "Send to the admission gate",
    "decision.dismiss": "Dismiss",
    "decision.dismissHint": "Clear this line of inquiry",
    "decision.challenge": "Challenge",
    "decision.challengeHint": "Test an innocent explanation",
    "decision.continue": "Keep investigating",
    "decision.continueHint": "Run more checks",
    "decision.send": "Send",
    "decision.placeholder": "Ask the agent, or leave an instruction…",
    "decision.conversation": "Conversation",
    "prompt.why": "Why is this suspicious?",
    "prompt.missing": "What evidence is still missing?",
    "who.auditor": "You",
    "who.agent": "Agent",

    "log.title": "Full investigation log",
    "log.events": "events",
    "log.none": "No events yet — advance the first step.",

    "kind.hypothesis_created": "Hypothesis proposed",
    "kind.tool_selected": "Tool selected",
    "kind.tool_result": "Tool result",
    "kind.counter_evidence": "Self-challenge",
    "kind.hypothesis_resolved": "Hypothesis resolved",
    "kind.auditor_message": "You",
    "kind.assistant_reply": "Agent",
    "kind.stopped": "Stopped",
    "kind.completed": "Completed",

    "drawer.title": "Source record",
    "drawer.snippet": "Exact source",
    "drawer.source": "Where it comes from",
    "drawer.kind": "Record type",
    "drawer.loading": "Fetching the source record…",
    "drawer.error": "Could not load this source record.",
    "drawer.missing": "No source record found for this evidence id.",
    "drawer.chain": "Chain of custody verified against the source hash at compile time.",
    "drawer.close": "Close",
    "sourceFile.title": "Source file",
    "sourceFile.loading": "Loading the source file…",
    "sourceFile.error": "Could not load the source file.",
    "sourceFile.unavailable": "Inline preview isn't available for this file type.",
    "sourceFile.download": "Download original",
    "sourceFile.open": "Open in new tab",
  },
  de: {
    "nav.caseBoard": "Fallübersicht",
    "nav.investigate": "Untersuchen",
    "nav.tagline": "Modelle verstehen. Code verifiziert. Prüfer entscheiden.",
    "lang.aria": "Sprache der Oberfläche",

    "page.title": "Untersuchungsbereich",
    "page.intro":
      "Übergeben Sie dem Agenten ein Dossier und ein Ziel. Er stellt Verdachtsmomente auf, führt forensische Prüfungen durch, testet unverdächtige Erklärungen und führt jede Zahl auf ihre Quelle zurück — die Entscheidung treffen Sie.",

    "banner.demo":
      "Demo-Modus — kein Live-Agent verbunden. Es wird eine Beispieluntersuchung angezeigt, damit Sie den Bereich erkunden können.",
    "banner.error": "Bei der Kommunikation mit dem Agenten ist ein Fehler aufgetreten.",
    "action.retry": "Erneut versuchen",
    "action.dismiss": "Schließen",
    "error.upload": "Das Dossier konnte nicht hochgeladen werden. Prüfen Sie die Datei und versuchen Sie es erneut.",
    "error.start": "Die Untersuchung konnte nicht gestartet werden.",
    "error.step": "Der Agent konnte diesen Schritt nicht abschließen.",
    "error.decision": "Ihre Entscheidung konnte nicht erfasst werden.",
    "error.message": "Ihre Nachricht konnte nicht gesendet werden.",
    "error.generic": "Die Anfrage an den Agenten ist fehlgeschlagen.",

    "badge.live": "Live",
    "badge.partial": "Teilweise",
    "badge.fallback": "Ersatz",
    "badge.planner": "Planer",

    "upload.dropTitle": "Falldossier ablegen oder Datei auswählen",
    "upload.dropHint":
      "Eine .zip mit Buchhaltungsexporten. Jede Zahl wird in einen Nachweis-Datensatz überführt, bevor ein Verdacht entsteht.",
    "upload.compiling": "Dossier wird verarbeitet…",
    "upload.compilingHint": "Exporte werden in nachvollziehbare Nachweis-Datensätze überführt.",
    "upload.ready": "Verarbeitet — bereit zur Untersuchung",
    "upload.sourceFiles": "Quelldateien",
    "upload.evidence": "Nachweis-Datensätze",
    "upload.entities": "Entitäten",
    "upload.events": "Vorgänge",
    "upload.objective": "Was soll der Agent untersuchen?",
    "upload.objectiveDefault":
      "Prüfen, ob das Lieferanten-Onboarding im 4. Quartal ein nicht offengelegtes Risiko durch nahestehende Personen oder eine Funktionstrennung verletzt hat.",
    "upload.begin": "Untersuchung beginnen",
    "upload.beginning": "Untersuchung wird geöffnet…",

    "toolbar.in_progress": "Läuft",
    "toolbar.awaiting_auditor": "Wartet auf Ihre Entscheidung",
    "toolbar.completed": "Abgeschlossen",
    "toolbar.stopped": "Gestoppt",
    "toolbar.advance": "Einen Schritt weiter",
    "toolbar.working": "Arbeitet…",
    "toolbar.runToEnd": "Bis zum Ende ausführen",

    "docket.title": "Untersuchungslinien",
    "docket.startHere": "Hier beginnen",
    "docket.priority": "Priorität {p}",
    "priority.high": "hoch",
    "priority.medium": "mittel",
    "priority.low": "niedrig",

    "status.proposed": "Vorgeschlagen",
    "status.active": "Aktiv",
    "status.submitted": "Eingereicht",
    "status.dismissed": "Verworfen",
    "status.insufficient": "Unzureichend",
    "status.awaiting_auditor": "Wartet auf Prüfer",

    "verdict.proposed": "Noch nicht geprüft",
    "verdict.active": "Wird geprüft",
    "verdict.submitted": "Empfiehlt Bestätigung",
    "verdict.dismissed": "Empfiehlt Verwerfen",
    "verdict.insufficient": "Nachweise unzureichend",
    "verdict.awaiting_auditor": "Ihre Entscheidung erforderlich",

    "file.chooseInquiry": "Wählen Sie eine Untersuchungslinie, um ihre Akte zu öffnen.",
    "file.amountAtRisk": "Betrag im Risiko",
    "file.notComputed": "Noch nicht berechnet",

    "evidence.title": "Nachweise",
    "evidence.supports": "Stützt den Verdacht",
    "evidence.innocent": "Unverdächtige Erklärungen",
    "evidence.stillNeeded": "Noch benötigt",
    "evidence.noneGathered": "Noch nichts gesammelt.",
    "evidence.noneFound": "Nichts gefunden — noch nichts entlastet.",
    "evidence.nothingOutstanding": "Nichts offen.",

    "tool.search_dossier": "Dossier durchsucht",
    "tool.cross_reference_hr_registry": "Personalregister abgeglichen",
    "tool.compute_exposure": "Risikobetrag berechnet",
    "tool.find_related_entities": "Verbundene Entitäten ermittelt",
    "checks.title": "Was der Agent geprüft hat",
    "checks.none": "Der Agent hat zu dieser Untersuchungslinie noch keine Prüfungen durchgeführt. Gehen Sie einen Schritt weiter.",
    "checks.calculation": "Berechnung",
    "checks.tracesTo": "Führt zurück auf",
    "checks.couldNotComplete": "Konnte nicht abgeschlossen werden",
    "checks.relationshipTail": "In der Beziehungskarte unten dargestellt.",

    "relmap.title": "Beziehungskarte",
    "relmap.show": "Zeigen, wie die Entitäten zusammenhängen",
    "relmap.none": "Noch keine Beziehungsdaten verfügbar.",

    "decision.title": "Ihre Entscheidung",
    "decision.confirm": "Feststellung bestätigen",
    "decision.confirmHint": "An die Zulassungsprüfung senden",
    "decision.dismiss": "Verwerfen",
    "decision.dismissHint": "Diese Untersuchungslinie schließen",
    "decision.challenge": "Anfechten",
    "decision.challengeHint": "Unverdächtige Erklärung testen",
    "decision.continue": "Weiter untersuchen",
    "decision.continueHint": "Weitere Prüfungen ausführen",
    "decision.send": "Senden",
    "decision.placeholder": "Fragen Sie den Agenten oder geben Sie eine Anweisung…",
    "decision.conversation": "Verlauf",
    "prompt.why": "Warum ist das verdächtig?",
    "prompt.missing": "Welche Nachweise fehlen noch?",
    "who.auditor": "Sie",
    "who.agent": "Agent",

    "log.title": "Vollständiges Untersuchungsprotokoll",
    "log.events": "Ereignisse",
    "log.none": "Noch keine Ereignisse — gehen Sie den ersten Schritt.",

    "kind.hypothesis_created": "Hypothese vorgeschlagen",
    "kind.tool_selected": "Werkzeug gewählt",
    "kind.tool_result": "Werkzeugergebnis",
    "kind.counter_evidence": "Selbstanfechtung",
    "kind.hypothesis_resolved": "Hypothese entschieden",
    "kind.auditor_message": "Sie",
    "kind.assistant_reply": "Agent",
    "kind.stopped": "Gestoppt",
    "kind.completed": "Abgeschlossen",

    "drawer.title": "Quellen-Datensatz",
    "drawer.snippet": "Exakte Quelle",
    "drawer.source": "Woher es stammt",
    "drawer.kind": "Datensatztyp",
    "drawer.loading": "Quellen-Datensatz wird geladen…",
    "drawer.error": "Dieser Quellen-Datensatz konnte nicht geladen werden.",
    "drawer.missing": "Kein Quellen-Datensatz für diese Nachweis-ID gefunden.",
    "drawer.chain": "Lückenlose Nachweiskette gegen den Quell-Hash zur Kompilierzeit verifiziert.",
    "drawer.close": "Schließen",
    "sourceFile.title": "Quelldatei",
    "sourceFile.loading": "Quelldatei wird geladen…",
    "sourceFile.error": "Die Quelldatei konnte nicht geladen werden.",
    "sourceFile.unavailable": "Für diesen Dateityp ist keine Inline-Vorschau verfügbar.",
    "sourceFile.download": "Original herunterladen",
    "sourceFile.open": "In neuem Tab öffnen",
  },
};

interface LangValue {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string, vars?: Record<string, string>) => string;
}

const LangContext = createContext<LangValue | null>(null);

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>("en");

  // Restore the persisted choice after mount. Starting from "en" on both server
  // and client keeps hydration stable; this corrects it once, client-side only.
  useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time sync from persisted preference
    if (stored === "de" || stored === "en") setLangState(stored);
  }, []);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    window.localStorage.setItem(STORAGE_KEY, l);
    document.documentElement.lang = l;
  }, []);

  const t = useCallback(
    (key: string, vars?: Record<string, string>) => {
      let str = STRINGS[lang][key] ?? STRINGS.en[key] ?? key;
      if (vars) for (const [k, v] of Object.entries(vars)) str = str.replace(`{${k}}`, v);
      return str;
    },
    [lang],
  );

  return <LangContext.Provider value={{ lang, setLang, t }}>{children}</LangContext.Provider>;
}

export function useLang(): LangValue {
  const ctx = useContext(LangContext);
  if (!ctx) throw new Error("useLang must be used within LanguageProvider");
  return ctx;
}

// Pick the selected-language variant of a possibly-bilingual backend value.
// Accepts a plain string (returned as-is) or an object carrying language
// variants ({en, de} / {en_US, de_DE} / {english, german} / {text}). Never
// machine-translates — only selects what the backend already provided.
export function localizeText(value: unknown, lang: Lang): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "object") {
    const o = value as Record<string, unknown>;
    const byLang =
      lang === "de"
        ? o.de ?? o.de_DE ?? o.german
        : o.en ?? o.en_US ?? o.english;
    const pick = byLang ?? o.en ?? o.de ?? o.text ?? o.value;
    if (typeof pick === "string") return pick;
  }
  return String(value);
}
