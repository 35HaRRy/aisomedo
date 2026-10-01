# Issue #27 — Web resumable upload verification

Verified on 2026-10-01 in `feat/issue-27-web-upload`, isolated worktree.
Approved design: `docs/superpowers/specs/2026-10-01-web-resumable-upload-design.md`.

## Acceptance coverage

| Issue requirement | Evidence |
| --- | --- |
| Progress, pause, retry | `transfer.test.ts`, `controller.test.ts`, `UploadPanel.test.tsx`, `UploadFlow.test.tsx`: backend-confirmed byte progress, single-file scheduling, accepted chunk with lost response, pause releasing next row, explicit retry using the same upload ID. |
| Resume after interruption | Identity/storage/controller tests plus actual API-wrapper flow tests: metadata-only reload, original-file reselection, same-name/same-size wrong-content rejection, changed modification time accepted, bounded 2 MiB hashing, confirmed ranges skipped. |
| Size rejection and invalid-media feedback | Authenticated/configurable read-only limits API tests; no initiation or hashing for local oversize/empty files; backend capacity rejection sends no ranges; worker diagnostics render as text; only `finalized` displays success. |

Upload browser tests reside in `web/src/uploads/`; backend limits tests in
`backend/tests/test_upload_limits_api.py`. Existing transport, shell, onboarding,
and session tests remain enabled.

## Commands and results

Run from repository root:

| Command | Result |
| --- | --- |
| `npm --prefix web test` | 156 tests passed. |
| `npm --prefix web run typecheck` | Passed. |
| `npm --prefix web run build` | Passed. |
| `uv run --project backend pytest backend/tests -v` | 133 passed; existing Starlette/httpx deprecation warning. |
| `uv run --project backend ruff check backend/src backend/tests` | **Not passing:** four pre-existing E501 lines in `deps.py:139` and `routes/meta.py:125,169,189`. These files are unchanged against branch base `48749a9`. |
| `uv run --project backend mypy backend/src/backend` | Passed, 22 source files. |
| `uv run --project backend python backend/scripts/export_openapi.py` | Passed; 59 paths. |
| `uv run --project backend python backend/scripts/generate_clients.py` | Passed. Kotlin output unchanged. |
| `git diff --exit-code -- backend/openapi.json web/src/api/openapi.ts android/app/src/main/java/com/dojo/aisomedo/api/GeneratedApi.kt` | Passed after regeneration: no contract drift. |
| `git diff --check` | Passed. |

Baseline before changes: 70 web tests, 129 backend tests. `npm ci` reported
three moderate and one high existing dependency vulnerabilities; no dependency
changes or automatic audit fixes were made.

## Browser acceptance

Chromium via Playwright against local Vite (`127.0.0.1:5179`), with all `/api/`
requests intercepted. Fixtures captured chunk bodies; no media reached a live
backend or production service. Final run had zero unexpected API paths and zero
page errors, with two uploads and three range requests total.

- Desktop 1440×1000: labelled native picker, keyboard focus and pause activation,
  visible filename/progress, paused upload with first 2 MiB accepted before its
  response arrived. Confirmed progress remained zero until reconciliation.
- Reload: original-file picker appeared; same-name/same-size changed content was
  rejected inline without another range request. Correct reselection resumed the
  same ID, sending only the remaining three bytes of a 2 MiB + 3-byte fixture.
- Mobile 320×900: long filename and reselection label wrapped; measured document
  width did not exceed viewport. First inspection caught implicit grid-track
  min-content overflow; explicit bounded tracks and label wrapping fixed it.
- Queued → processing → finalized showed success only at finalization. A second
  upload transitioned to failed with visible `invalid JPEG contents` diagnostic
  and an explicit new-upload action.
- Configured two-byte limit rejected a three-byte file before initiation.
- Keyboard Enter opened the native chooser; MCP stops execution at that modal,
  so fixture population used Playwright `setInputFiles`. Pause used keyboard Enter;
  fresh-retry action was independently keyboard-focusable.

Desktop/mobile screenshots were inspected in one batched defect pass and one
confirmation pass. Temporary browser/server were stopped after verification.

## Limits and deliberate scope

- No live multi-gigabyte transfer, real media worker processing, mobile-device
  browser, Firefox/WebKit, or manual screen-reader session was exercised.
  Worker outcomes were deterministic API fixtures; backend suite tested the
  existing backend behavior independently.
- Recovery stores client-scoped metadata only, never file contents or tokens.
  Reload requires the original file; blocked/quota-failed storage warns that
  reload recovery is unavailable while allowing in-memory transfer.
- Losing initiation's response leaves no known upload ID and sends no media.
  Explicit retry can leave an empty orphan for existing backend cleanup.
- Filename conflicts stop transfer. Rename/overwrite resolution remains #28.
  No new dependencies, background upload, cross-tab lock, or idempotency protocol.
- Whole-branch independent review is required before the final handoff; findings
  and verified corrections are recorded below when that review finishes.
