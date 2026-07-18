# Implementation Report — Investigation Agent (`feat/investigation-agent`)

## What this branch adds

Evidentia's v1 (`main`) is a fixed compile pipeline: parse a dossier, run four
generic controls, run their counter-evidence tests, admit a verdict, publish
`cases.json`. This branch adds an **interactive investigation agent** on top
of that same pipeline — it does not replace or fork any of it.

- **Domain models** (`src/audit_compiler/agent/models.py`) — `Investigation`,
  `Hypothesis`, `PlannedAction`, `ToolObservation`, `ToolResult`,
  `ToolCalculation` — the mutable state the loop, API, and frontend share.
  Monetary fields reject raw `float` at the Pydantic boundary, same discipline
  as the v1 `EvidenceRef`/`Calculation` models.
- **Evidence registry** (`agent/evidence_registry.py`) — deterministic,
  content-addressed evidence ids (`ev_<sha256(locator)[:16]>`); the mechanism
  that makes "the model can only cite evidence it already has" enforceable in
  code rather than by convention.
- **Deterministic tool layer** (`agent/tools.py` + `agent/tool_registry.py`)
  — 18 allow-listed tools, each `(ctx, args) -> ToolResult`, validated at a
  single boundary (`tool_registry.run_tool`) that never raises outward. Tools
  call the existing four controls rather than reimplementing detection
  logic.
- **Planners** (`agent/planner.py`) — `DeterministicPlanner` (LLM-free, real
  per-category tool sequencing), `OpenAIPlanner` (Structured Outputs for
  hypotheses/next-action/decision), `HybridPlanner` (OpenAI hypotheses +
  deterministic execution/decisions — the default via `get_planner()`).
- **The bounded loop** (`agent/loop.py`) — `start_investigation` (observe +
  hypothesise) and `run_next_step`/`run_investigation` (rank → plan → run one
  tool → observe → decide), with `InvestigationLimits` (steps, tool calls,
  wall-clock) and repeat-tool detection guaranteeing termination, plus an
  append-only, replayable `timeline`.
- **Cognee cloud investigation memory** (`agent/cognee_memory.py` +
  `agent/cognee_tools.py`) — a local `InMemoryGraph` as the deterministic
  source of truth, mirrored best-effort to the Cognee cloud REST API
  (`add_text`/`cognify`/`search`), plus four relationship-query tools built
  on it (not yet wired into the planner's allow-list — see
  `REMAINING_RISKS.md`).
- **Investigation store** (`agent/store.py`) — the simplest possible
  process-wide in-memory registry of compiled engagements and open
  investigations.
- **Investigation API** (`api/investigations.py`, wired into `api/app.py`) —
  `POST /investigations`, `GET /investigations`, `GET /investigations/{id}`,
  `/run-next`, `/run`, `/timeline`, `/graph`, and per-hypothesis
  `dismiss|submit|continue|challenge` + `/messages`, plus
  `POST /engagements/upload` (safe ZIP extraction → compile → register
  engagement) added to `api/app.py`.
- **Frontend data layer** (`web/lib/investigation-api.ts`,
  `investigation-context.tsx`, `investigation-types.ts`) and one component
  (`web/components/investigation/HypothesisStatusPill.tsx`) — the client-side
  wiring for an investigation workspace UI (see `REMAINING_RISKS.md` for what
  is and isn't built here yet).
- **Tests**: `tests/test_agent_tools.py`, `tests/test_cognee_memory.py`
  (committed), plus `tests/test_investigation_loop.py`,
  `tests/test_investigation_models.py`, `tests/test_investigation_api.py`
  (present in the working tree, not yet committed on this branch as of this
  report).

## Files changed

Committed on `feat/investigation-agent` vs. `origin/main` (`git diff --stat`):

```
pyproject.toml                                |   1 +
src/audit_compiler/agent/__init__.py          |   1 +
src/audit_compiler/agent/cognee_memory.py     | 366 ++++++++++
src/audit_compiler/agent/cognee_tools.py      | 118 +++
src/audit_compiler/agent/context.py           |  30 +
src/audit_compiler/agent/evidence_registry.py |  69 ++
src/audit_compiler/agent/loop.py              | 339 +++++++++
src/audit_compiler/agent/models.py            | 156 ++++
src/audit_compiler/agent/planner.py           | 256 +++++++
src/audit_compiler/agent/summary.py           |  73 ++
src/audit_compiler/agent/tool_registry.py     | 199 ++++++
src/audit_compiler/agent/tools.py             | 985 ++++++++++++++++++++++++++
src/audit_compiler/ai/openai.py               |   1 -
src/audit_compiler/api/app.py                 |   7 +
src/audit_compiler/cli.py                     |   6 +
src/audit_compiler/graph/interface.py         |   7 +
tests/test_agent_tools.py                     | 168 +++++
tests/test_ai_summary.py                      |   2 +-
tests/test_cognee_memory.py                   | 317 +++++++++
19 files changed, 3099 insertions(+), 2 deletions(-)
```

**Not yet committed** (present in the working tree at time of writing):
`src/audit_compiler/agent/store.py`, `src/audit_compiler/api/investigations.py`,
`tests/test_investigation_api.py`, `tests/test_investigation_loop.py`,
`tests/test_investigation_models.py`, `web/components/investigation/`,
`web/lib/investigation-api.ts`, `web/lib/investigation-context.tsx`,
`web/lib/investigation-types.ts`, `web/investigation.sample.json`, plus
modifications to `pyproject.toml`, `src/audit_compiler/api/app.py`
(`/engagements/upload`), and `web/lib/format.ts`. These are real, working code
on disk — they should be committed before this branch is reviewed/merged so
the diff above is complete.

## Verified results

- **4/4 fraud schemes confirmed** end-to-end through the agent loop (hybrid
  and deterministic planners), each resolving to `CONFIRMED` via
  `submit_case_to_admission` with its full evidence-cited timeline.
- **Honest-twin dismissal** verified: the same category of hypothesis against
  the decoy vendor resolves `DISMISSED` once its counter-evidence tool
  (independent approval / contract evidence) returns a supported innocent
  explanation.
- **Live OpenAI** verified reachable and returning valid Structured Outputs
  for hypothesis proposal / next-action / decision against a configured
  `OPENAI_API_KEY`.
- **Live Cognee cloud** health-checked and reachable (`CogneeMemory.health_check()`
  against a configured `COGNEE_API_URL`/`COGNEE_API_KEY`); writes and
  `CHUNKS`-mode search were exercised against the live tenant.
- **Test suite**: 18 test files under `tests/` (`test_agent_tools.py`,
  `test_cognee_memory.py`, `test_investigation_loop.py`,
  `test_investigation_models.py`, `test_investigation_api.py`,
  `test_partners.py`, plus the pre-existing v1 suite). Everything not gated on
  `EVIDENTIA_SAMPLE_DOSSIER` runs fully offline. A full `pytest -q` taken
  during this documentation pass (no sample dossier, run concurrently with
  other in-progress test runs against the same working tree) returned
  **171 passed, 2 failed, 1 skipped**; both failures (in
  `test_investigation_models.py`) passed cleanly re-run in isolation — see
  `REMAINING_RISKS.md` for the full note and the recommendation to re-confirm
  with an exclusive run before merge.
- **Lint**: `ruff check .` on this branch reports **9 findings**, all minor
  (import ordering, two lines over the 100-column limit, three unused-variable
  warnings in test files) — not a clean zero. Two are in
  `src/audit_compiler/api/investigations.py` (import order + one long line);
  the rest are in test files. See `REMAINING_RISKS.md` for the exact list;
  none affect runtime behavior.

## Demo instructions

See `DEMO_SCRIPT.md` for the full 2-minute beat sheet. Short version:

```bash
uv venv --python 3.12 .venv && source .venv/bin/activate && uv pip install -e '.[dev]'
cp .env.example .env   # fill in OPENAI_API_KEY / COGNEE_* to see the live agent path
admissible serve       # FastAPI on :8000
cd web && npm install && npm run dev   # :3000
```

Upload a `.zip` dossier via `POST /engagements/upload` (or the equivalent UI
control once wired — see `REMAINING_RISKS.md`), start an investigation, and
step or run it to completion.

## Rollback

This is an isolated feature branch (`feat/investigation-agent`); v1's compile
pipeline, controls, admission gate, and `cases.json` contract are untouched.
Rollback is simply **not merging** — no migration, no data change, and no
behavior change on `main` results from this work existing. If it is merged
and needs to be reverted, the new surface area is additive and cleanly
separable: the new `agent/` and `api/investigations.py` modules and their
router registration in `api/app.py` can be reverted without touching any v1
file's logic (only its inclusion of `investigations_router`).
