# Demo Script (~2 minutes)

Goal: prove the thesis on screen — an agent that decides where to look,
deterministic proof for every claim it makes, and a human sign-off — using
one confirmed fraud case, one honest twin, and the exact evidence behind both.

| Time | On screen | Narration |
|------|-----------|-----------|
| 0:00–0:15 | Browser: drag a `.zip` dossier onto the upload panel. It uploads, extracts, and compiles; a fresh `engagement_id` appears and the investigation workspace opens. | "This is Evidentia — an audit investigation agent. We hand it a dossier we've never shown it before, zipped up. It extracts safely, compiles every source natively — GDPdU, spreadsheets, invoices — and it's ready to investigate." |
| 0:15–0:35 | The agent's first move renders on screen: 3–5 ranked hypotheses, each with a claim, category, and priority — one calls out a specific vendor as suspicious. | "It doesn't run a checklist. It looks at what actually parsed — vendors, users, postings — and proposes what's worth chasing: a vendor that looks self-approved, a cluster of payments, a capitalised repair, a period cut-off. It ranks them itself." |
| 0:35–1:10 | Click into the top hypothesis (the suspicious vendor). Timeline fills in live, one tool at a time: `check_vendor_creation_and_approval` → self-approved, flagged; `check_user_permissions` → toxic create+post+pay combo; `reconcile_vendor_invoices_and_payments` → unreconciled gap; `find_contract_or_service_evidence` → nothing found; `find_independent_approval` → nothing found; `compare_peer_vendors` → far above peer median. Pause on one result and click its cited number — it jumps to the exact source row/cell. | "Watch it work: it checks who created and approved this vendor — same person, no independent sign-off. It checks that person's permissions — they can create, post, *and* pay. It reconciles the invoices against the payments. Then it goes looking for reasons this could be innocent — a contract, an independent approval — and finds none. Every one of these numbers is real and clickable; this one jumps straight to the source cell it came from." |
| 1:10–1:25 | The agent submits: `submit_case_to_admission` fires, the admission-gate verdict lands as `CONFIRMED`, with the calculation panel (expression, inputs, SQL) visible. | "Because the required counter-checks all came back empty, it submits the case — and the admission gate, not the model, is what stamps this `CONFIRMED`. The exposure number is SQL against our DuckDB ledger, not a model's guess." |
| 1:25–1:50 | Switch to the second hypothesis: a different, newer vendor — the honest twin. Same tool sequence runs, but this time `find_independent_approval` and `find_contract_or_service_evidence` both come back positive, with their own cited evidence. The hypothesis resolves `DISMISSED`. | "Now the honest twin — a new vendor that looks similar on the surface. Same investigation, same tools. But this time it finds a second, independent approver, and a real, documented contract. It dismisses this one — correctly. Telling these two apart, with evidence, is the whole point." |
| 1:50–2:00 | Cut to the case board / source viewer for a beat, then title card. | "Models understand. Code verifies. Auditors decide." |

## Setup notes for recording

- Pre-zip the sample dossier so the upload step is instant and deterministic;
  re-record live only if timing allows.
- Have the OpenAI hybrid planner configured for the take so hypothesis
  generation reads naturally on screen — the deterministic planner is a fine
  fallback for a dry run, but the hybrid narration ("it decides") is stronger
  with a live model.
- Pre-run the investigation once so you know exactly which hypothesis lands
  on the confirmed vendor and which lands on the honest twin, and bookmark
  both — don't discover this live.
- Keep the "click a cited number" moment slow enough to read the source
  viewer highlight — it's the single most important beat for the
  false-positive/provenance thesis.
- If time is short, cut nothing from the two hypothesis walk-throughs; trim
  the opening upload beat to a single cut instead.
