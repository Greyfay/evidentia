# Investigation source-file preview

**Date:** 2026-07-18
**Status:** Approved
**Scope:** `/investigate` path only (the compiled-cases viewer runs on a static fixture with no real files behind it, so "open the uploaded file" does not apply there).

## Problem

When the investigation agent cites a finding, the evidence drawer shows an extracted
snippet plus a human-readable source string (e.g. `ledger.csv · row 42`). The auditor
cannot open the **actual original file they uploaded** to verify the finding in context
before deciding to dismiss or submit it.

The originals are already on disk: `upload_engagement` copies the dossier to a durable
directory, and DuckDB persists `dossier_root`, so `ctx.dossier.root / source_path` is the
exact uploaded file. Nothing currently serves it.

## Design

### Backend — `src/audit_compiler/api/investigations.py`

1. **Extend** `GET /investigations/{id}/evidence/{evidence_id}` to also return
   `source_path`, `locator`, and `file_sha256` alongside the existing `kind` / `source` /
   `snippet`. The client needs these to choose a viewer and deep-link the cited page/row.

2. **New** `GET /investigations/{id}/evidence/{evidence_id}/source-file`:
   - resolve the evidence id via `ctx.registry.resolve(evidence_id)` → `source_path`
   - `root = ctx.dossier.root`
   - serve `root / source_path` as a `FileResponse`, media-type guessed by extension,
     `Content-Disposition: inline` (so the browser renders PDFs/text in place).

3. **Shared helper** `_serve_source_file(root, source_path)` performing path-traversal-safe
   resolution — the resolved path must stay under `root` — and returning `FileResponse`,
   raising 404 when the evidence id is unknown or the file is missing.

### Frontend

1. `web/lib/investigation-api.ts`
   - extend the evidence-detail type with `source_path`, `locator`, `file_sha256`
   - add `sourceFileUrl(investigationId, evidenceId)` returning the absolute
     `${API_BASE}/investigations/{id}/evidence/{evidence_id}/source-file`.

2. **New** `web/components/investigation/SourceFilePreview.tsx` — picks a viewer by the
   `source_path` file extension:
   - `.pdf` → `<iframe src={url + "#page=" + locator.page}>` (native render, jump to cited page)
   - `.csv` / `.txt` → fetch the text, render in a scrollable `<pre>`, highlight the cited
     row when `locator.row` is known
   - `.xlsx` / `.docx` / other → "inline preview not available for this file type" plus a
     **Download original** link
   - loading and error states; on any load failure, degrade to a download link.

3. `web/components/investigation/InvestigationEvidenceDrawer.tsx` — add a "Source file"
   section rendering `SourceFilePreview` below the source/kind grid.

4. `web/lib/i18n.tsx` — add DE/EN keys for the new labels (drawer section title,
   download link, preview-unavailable, loading/error).

### Error handling

The endpoint 404s cleanly for an unknown evidence id or a missing file. The component
degrades to a download link on any load failure. The traversal guard rejects any
`source_path` that resolves outside the dossier root.

## Testing

- **Backend pytest** (primary safety net): compile a tiny dossier → start an investigation
  → cite an evidence id → assert `source-file` returns 200 with bytes matching the original;
  404 on an unknown id; the extended evidence response carries `source_path` / `locator` /
  `file_sha256`; the traversal guard holds for a crafted path.
- **Frontend**: typecheck + production build. Per `web/AGENTS.md`, consult
  `web/node_modules/next/dist/docs/` before writing any Next code.

## Out of scope

- The compiled-cases viewer (`/case/[id]`) — static fixture, no real files.
- Full inline rendering of `.xlsx` / `.docx` (download fallback instead).
