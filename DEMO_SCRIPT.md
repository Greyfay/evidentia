# Demo Script (~2 minutes)

Goal: prove the thesis on screen — deterministic proof, model-assisted
understanding, human sign-off — using one confirmed fraud case and its
honest twin.

| Time | On screen | Narration |
|------|-----------|-----------|
| 0:00–0:20 | Terminal: run `admissible compile <dossier> --cases-out web/public/cases.json`. Output scrolls: source inventory (GDPdU, CSV, XLSX, DOCX, PDF, each with status/rows/sha256) then a reconciliation summary. Cut to the compiler screen in the console showing the same counts. | "This is Evidentia. We hand it a raw, mixed German/English accounting dossier — GDPdU exports, spreadsheets, policy documents, scanned invoices — and it compiles every source natively. No file goes to a model just to be read. Every row, cell, and page gets hashed and reconciled before anything else happens." |
| 0:20–0:55 | Open the case board, filtered to `CONFIRMED`. Click the headline vendor-override case. Walk the evidence chain top to bottom; click one cited number — it jumps to the exact source row/cell/page, highlighted. Then show the calculation panel: expression, inputs, and the actual SQL that produced the result. Scroll to counter-tests: each refuter (independent approval, contract, deliverable, prior history) shown as tested and absent. | "Here's the headline case: one user creates a vendor, approves it, posts the invoices, and executes the payment — no independent sign-off anywhere in the chain. Every number here is clickable — this one jumps straight to the source cell it came from. The calculation isn't a model's guess, it's the SQL that ran against our DuckDB ledger, and you can re-run it. And this case didn't just get flagged — we tested it against every counter-explanation a real auditor would ask for: independent approval, a contract, an actual delivery. None of them held. That's why it's confirmed." |
| 0:55–1:35 | Switch to the honest-twin case: same control (vendor integrity), different vendor. Open its case file — status `DISMISSED`. Point at the counter-test that cleared it (independent approval by a second user + matched real deliveries), with its own evidence citations. | "Same control, different vendor — and this one gets dismissed. It looks similar on the surface: a new vendor, invoices, payments. But here the approval came from a second, independent user, and the deliveries are real and documented. Dismissing this correctly is just as important as catching the first one — a system that can't tell these apart isn't auditable, it's just noisy. That dismissal is not a fallback, it's a real, evidenced verdict." |
| 1:35–1:55 | Quick cut: case board zoomed out showing the mix of `CONFIRMED` / `HUMAN_REVIEW` / `DISMISSED` across all four controls, then a glimpse of the `.env` with no keys set (or panel showing "OpenAI: not configured") to show the compile still ran end to end. | "This all runs the same way whether the model layer is here or not — the model only interprets language and drafts hypotheses and explanations; it can never invent a number or override this gate. And this exact pipeline, unmodified, is what will run against the dossier none of us have seen yet." |
| 1:55–2:00 | Title card / tagline. | "Models understand. Code verifies. Auditors decide." |

## Setup notes for recording

- Pre-compile the sample dossier once so the terminal segment is fast and
  deterministic; re-run live only if timing allows.
- Have the case board pre-filtered/bookmarked to the two cases used (headline
  `CONFIRMED` vendor case, honest-twin `DISMISSED` case) to avoid dead air
  navigating.
- Keep the "click a cited number" moment slow enough to read the source
  viewer highlight — it's the single most important beat for the false-
  positive/provenance thesis.
- If time is short, cut the 1:35–1:55 beat first; keep the two case walk-
  throughs and the closing tagline intact.
