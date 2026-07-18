# Evidentia — Final Report

Evidentia is a provenance-first **audit investigation agent**. An auditor uploads a
financial dossier (`.zip` of accounting exports); the system compiles every source
into evidence records, an agent proposes ranked suspicions, runs deterministic
forensic tools, tests innocent explanations, explores a relationship graph, and an
admission gate stamps each line of inquiry `CONFIRMED` / `HUMAN_REVIEW` / `DISMISSED`.
Every figure traces to its exact source. **Models understand. Code verifies. Auditors decide.**

## What changed in this round

| PR | Area | Summary |
|----|------|---------|
| #3 | full flow | Fixed two runtime bugs that forced the live UI into demo-fixture mode (dropped `engagement_id` → 422; tool-result object rendered as a React child). Added `GET /agent-status`; wired a live Cognee relationship tool into the loop; UI mode badge + kept the fixture out of live mode. |
| #5 | api / agent | `GET /investigations/{id}/evidence/{id}` resolves a real `ev_…` id to its exact source (`{evidence_id, kind, source, snippet}`). Grounded auditor answers: `POST /messages` returns `assistant_reply` derived strictly from real investigation state, citing only evidence ids that exist. |
| #6 | web | Redesigned the Investigation Workspace for the auditor persona (docket of lines of inquiry → focused case file → decision bar). DE/EN toggle. Robust native-`<label>` upload. Evidence + graph read from the API; live errors show a retry state instead of silently swapping in demo data. |
| #7 | controls | Generic, deterministic **anomaly-discovery control** (round/large postings, duplicated document+amount, Benford first-digit) — review-needed leads only, never a verdict. Wired into `default_controls()` with the four-scheme regression still green. |

## The live flow (verified end-to-end)

Upload dossier `.zip` → secure extraction + compile → ranked hypotheses → agent selects
forensic tools → observations update the plan → counter-evidence tested → **live Cognee
relationship lookup** → deterministic DuckDB calculations → admission evaluates the real
investigation → auditor opens the exact source behind any number → `CONFIRMED` /
review / `DISMISSED`.

On the sample dossier the four schemes confirm with their exact exposures
(vendor integrity 295,120 · cut-off 192,000 · capitalisation 150,800 · split payment
39,040) and the honest-twin vendor is dismissed.

## Exact OpenAI usage

- `OPENAI_API_KEY` present ⇒ `get_planner()` returns the **HybridPlanner** (default):
  OpenAI proposes and ranks hypotheses and phrases auditor-facing explanations /
  grounded answers; a deterministic per-category plan drives tool execution and the
  admission gate owns every verdict.
- The model **never** computes a monetary total or declares a verdict. Grounded answers
  strip any evidence id the model cites that is not already in the investigation.
- Without the key the DeterministicPlanner runs the same investigation, LLM-free.

## Exact Cognee usage

- Investigation memory graph (local `InMemoryGraph` mirror + best-effort Cognee cloud).
- `find_related_entities` is an allow-listed **agent tool** the loop runs during the
  vendor line of inquiry: it seeds the subject + evidence into the graph and returns
  relationship context plus a live Cognee cloud `CHUNKS` search (`provider:
  in_memory+cognee`, `cloud_enrichment`), shown in the timeline and the UI relationship map.
- DuckDB/Python remain authoritative for money; Cognee only ever returns relationships.

## Mode transparency

`GET /agent-status` → `{mode: live|partial|fallback, planner, openai:{active,model},
cognee:{active}}`. The UI header shows this (e.g. `Live · OpenAI + Cognee · planner: hybrid`).

## Test commands & results

```
# backend (needs the sample dossier for the gated regression/e2e tests)
EVIDENTIA_SAMPLE_DOSSIER="<dossier dir>" uv run --extra dev pytest tests/ -q
# web
cd web && npm run lint && npm run build
```

- `tests/test_controls_regression.py` (four schemes confirmed + honest twin dismissed): **passing**.
- New backend tests (evidence endpoint, grounded messages, anomaly control): **passing**.
- Web lint + production build: **passing**.
- Full backend suite result recorded at merge time; see CI / the merge run.

> Note: the compiler writes a `.admissible/*.duckdb` cache into the dossier root; if the
> `test_sample_dossier_compiles_and_runs` upload test fails on size, delete that cache
> (it can grow across repeated compiles) — the raw dossier is only a few MB.

## Live demo

1. `admissible serve` (API :8000) with `OPENAI_API_KEY` + `COGNEE_*` set in `.env`.
2. `cd web && npm run dev` (:3000) → open `/investigate`.
3. Drop the dossier `.zip`, give an objective, **Begin investigation**, **Run to end**.
4. Read the verdict + exposure; ask "Why is this suspicious?" → grounded answer with
   clickable evidence; click an evidence id → exact source; open the relationship map.

## Remaining risks

- Cognee cloud `add_text`/`cognify` is slow; the loop seeds the graph **locally** and
  relies on the faster `CHUNKS` search for live enrichment, so the cloud mirror can lag
  the local graph.
- Pure-OpenAI tool selection is in-path but less reliable within the step limits;
  Hybrid is the default for that reason.
- Two control implementations still coexist in `controls/`; `default_controls()` is the
  single source of truth for what the agent actually runs.
