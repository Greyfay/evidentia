# Remaining Risks — Investigation Agent

An honest list of what is not yet solid on `feat/investigation-agent`,
written for whoever reviews or demos this next.

## Planner reliability

- **Pure `OpenAIPlanner` mode is in-path and live, but less reliable within
  the loop's step limits.** When the LLM also picks the next tool
  (`next_action`) instead of the deterministic per-category plan, it can
  reorder or skip a required counter-evidence tool, or repeat a tool
  (triggering the loop's force-closure-to-submit fallback) before the
  investigation would otherwise have converged. **`HybridPlanner` is the
  default** returned by `get_planner()` whenever `OPENAI_API_KEY` is set
  precisely to avoid this: OpenAI's judgement only shapes *which*
  hypotheses get proposed and ranked, while a deterministic, tested
  per-category tool sequence drives execution and the final decision. Do
  not switch the default to pure `OpenAIPlanner` without re-validating
  against the step/tool-call limits in `InvestigationLimits`.

## Cognee cloud latency

- Cognee cloud's `/api/v1/search` in its default `GRAPH_COMPLETION` mode
  triggers a server-side LLM synthesis step and is noticeably slow —
  `CogneeMemory` deliberately calls it with `searchType="CHUNKS"` instead
  (direct lexical/vector lookup) for every enrichment call, trading semantic
  richness for latency the agent loop can actually afford mid-investigation.
- All Cognee cloud enrichment is **best-effort only**: a slow, unreachable,
  or erroring call is caught, logged, and swallowed — the local
  `InMemoryGraph` mirror is unaffected and remains the source of truth for
  every structural query the agent or API relies on. This means the graph
  view can silently be less rich than intended without any visible error; if
  Cognee latency/availability regresses further, consider a background
  refresh instead of a synchronous best-effort call, and/or surfacing
  `.available`/timing in the API response so a slow cloud path is visible
  rather than just silently thin.

## Cognee relationship tools are not wired into the planner

- `agent/cognee_tools.py` defines four tools (`find_related_entities`,
  `find_similar_investigation_paths`, `find_other_vendors_connected_to_user`,
  `retrieve_open_hypothesis_context`) in the same `(ctx, args) -> ToolResult`
  shape as the deterministic forensic tools, but `COGNEE_TOOLS` is **not**
  merged into `tool_registry.TOOLS`. The planner cannot currently select
  them, and `loop.py` never calls into `cognee_memory` at all — the only
  place the investigation's Cognee mirror gets populated today is
  `GET /investigations/{id}/graph`, which calls
  `memory.remember_investigation(inv)` on read. Net effect: the "memory
  connects the investigation" story is real at the data-model level
  (`CogneeMemory`, the graph interface, the tools) but not yet exercised by
  the agent's own decision loop. Wiring `COGNEE_TOOLS` into the allow-list
  and giving the planner a reason to call them (e.g. "have we seen this
  category before across investigations?") is the natural next step.

## Sample test suite performance

- The sample-dossier regression suite and the mutation-testing suite (gated
  behind `EVIDENTIA_SAMPLE_DOSSIER`) reload and recompile the sample dossier
  from scratch per test, at roughly **~95 seconds** for the full gated suite.
  Every other test in the repo runs offline and fast. A session-scoped
  pytest fixture that compiles the sample dossier once and reuses the
  `AgentContext`/bundle across tests in that suite would cut this
  significantly; not done here to avoid touching `tests/`.

## Full-suite run had 2 failures under concurrent load

- A full `pytest -q` run taken during this documentation pass (no
  `EVIDENTIA_SAMPLE_DOSSIER` set) returned **171 passed, 2 failed, 1
  skipped** in `tests/test_investigation_models.py`
  (`TestEnumMembers::test_investigation_status_members`,
  `TestMonetaryFieldRejectFloat::test_hypothesis_candidate_exposure_accepts_string`).
  Both passed cleanly when re-run in isolation immediately after, and the
  run overlapped with several other concurrent `pytest` invocations against
  the same working tree (teammates independently validating other test
  files at the same time). This looks like resource contention/flakiness
  under concurrent load rather than a real regression, but it was not
  re-confirmed with an isolated, exclusive full-suite run — do that once
  before merge.

## Two parallel control implementations coexist

- `src/audit_compiler/controls/` currently has **two independent sets** of
  control modules: `vendor_sod.py` / `split_payment.py` /
  `capitalisation.py` / `cutoff.py` (this branch's dependency, British
  spelling) and `vendor_integrity.py` / `split_payments.py` /
  `capitalization.py` (a teammate's parallel implementation, American
  spelling, plural `split_payments`). **`controls/registry.py`'s
  `default_controls()` — and therefore every agent tool and the loop — uses
  the `vendor_sod` set exclusively** (`_CONTROLS_BY_ID`,
  `_PLAN`/`_CATEGORY_CONTROL` in `agent/planner.py` and `agent/loop.py` key
  off `vendor_sod`/`split_payment`/`capitalisation`/`cutoff` ids). The other
  module set is not imported by `registry.py` and is not reachable from the
  agent. If/when these two implementations are reconciled, double-check that
  `default_controls()`, `agent/tools.py`'s `_CONTROLS_BY_ID`, and the
  `_CATEGORY_HINT`/`_CATEGORY_CONTROL` maps all continue to point at
  whichever set wins — a silent mismatch here would make the agent's
  category labels (`HypothesisCategory.VENDOR_INTEGRITY`, etc.) and the
  actual control id it runs (`vendor_sod`) diverge in confusing ways.

## Frontend investigation UI is partially built

- The data layer for an investigation workspace is in place
  (`web/lib/investigation-api.ts`, `investigation-context.tsx`,
  `investigation-types.ts`) plus one presentational component
  (`web/components/investigation/HypothesisStatusPill.tsx`), but there is
  **no dedicated investigation workspace route/page** yet under `web/app/`
  (only `web/app/page.tsx` and `web/app/case/[id]/page.tsx` exist). The demo
  script's on-screen beats (live hypothesis list, live timeline, click-to-
  source) assume this page exists — build and verify it end-to-end before
  relying on `DEMO_SCRIPT.md` as written; the API it needs to call is
  already live and tested independently of the UI.

## Lint is not fully clean

- `ruff check .` on this branch currently reports **9 findings**: an
  unsorted import block and one over-length line in
  `src/audit_compiler/api/investigations.py`, and five minor issues
  (unused imports/variables, two over-length lines) across
  `tests/test_investigation_loop.py` and `tests/test_investigation_models.py`.
  None affect runtime behavior; 3 are auto-fixable with `ruff check --fix`.
  Left as-is here since this pass is docs-only and those files were out of
  scope to edit.

## Uncommitted work on the branch

- Several files this report and the README/ARCHITECTURE updates describe are
  present in the working tree but **not yet committed**:
  `src/audit_compiler/agent/store.py`, `src/audit_compiler/api/investigations.py`,
  `tests/test_investigation_api.py`, `tests/test_investigation_loop.py`,
  `tests/test_investigation_models.py`, the `web/components/investigation/`
  + `web/lib/investigation-*` frontend files, and small edits to
  `pyproject.toml`, `src/audit_compiler/api/app.py`, and `web/lib/format.ts`.
  Commit these before opening the branch for review — as-is, `git log` alone
  understates what actually exists and works.

## Unverified-live claims to re-check before presenting

- "Live OpenAI" and "live Cognee cloud" verification in
  `IMPLEMENTATION_REPORT.md` reflect runs performed with real
  `OPENAI_API_KEY`/`COGNEE_API_URL`/`COGNEE_API_KEY` values configured at the
  time; this documentation pass did not re-run those live calls (no keys
  were exercised while writing these docs). Re-confirm both immediately
  before a live demo — API keys, quotas, or the Cognee tenant's availability
  can change between verification and presentation.
