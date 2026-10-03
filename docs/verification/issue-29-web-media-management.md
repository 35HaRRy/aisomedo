# Issue #29 — web media management verification

Branch: `feat/issue-29-media`; base: `1fc600d`.
Implementation commits: `9c377b3`, `9c679df`, `4427608`, `eeff5fa`,
`28380f8`, `46bc918`, `1ef2488`, plus verification/review commits following them.

## Behavior covered

- Retained source-time sections; canonical selections, legacy one-range
  compatibility and digest preservation until an explicit edit.
- Exact retained duration, photo/card duration once per montage, unknown
  source duration, and atomic rejection of invalid/over-limit changes.
- Real production FFmpeg rendering: ordered red/green/blue retained sections,
  distinct segment files, H.264 1080×1920 output, AAC source audio/generated
  silence, watermark and intro/outro durations, unchanged original bytes.
- Reversible removal/restoration, saved position/sections, persisted ordering,
  render staleness and same-minute package rollover identity guards.
- Paired browser/device authorization, revoked clients, private no-store
  byte ranges, Unicode attachment names, unavailable artifacts, traversal
  checks, and unchanged public approved-render signing restrictions.
- Session-owned drafts across video switches, invalid numeric text, uncertain
  writes, explicit refresh, stale snapshots, navigation/save/discard/cancel,
  session loss, cancellation and late responses.
- Active uploads retain original File references through completed browsing.
  Historical packages expose only read-only previews/downloads.

## Commands and results

Executed in the isolated Windows worktree with Docker available:

| Command (repository root unless noted) | Result |
| --- | --- |
| `uv run --project dojo-core pytest dojo-core/tests -v` | 640 passed, 4 skipped; new real-renderer checks executed |
| `uv run --project backend pytest backend/tests -v` | 155 passed |
| `uv run --project worker pytest worker/tests -v` | 140 passed |
| `npm test` (web) | 228 passed, 28 files |
| `npm run typecheck` (web) | Passed |
| `npm run build` (web) | Passed |
| `npm run test:browser` (web, `PLAYWRIGHT_PORT=3100`) | 4 passed: desktop 1280×900 and touch/mobile 390×844 |
| `uv run --project backend mypy backend/src/backend` | Passed |
| `uv run --project dojo-core mypy dojo-core/src/dojo` | Existing recovery notification dict-item mismatch; reproduced from base `1fc600d` |
| `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests` | 23 existing E501 findings; no newly introduced findings |
| `uv run --project backend ruff check backend/src backend/tests` | 4 existing E501 findings; no newly introduced findings |
| OpenAPI export + client generation, repeated with SHA-256 comparison | Byte-identical generated contracts |
| `git diff --check` | Checked at each commit; final confirmation below |

Baseline E501 findings were reproduced from `git show 1fc600d:<path>` in
isolated scratch copies and compared by source line (27 findings / 26 unique
lines). The core mypy failure is the same baseline recovery-notification
metadata inference error. Unrelated baseline lint/type failures are **not fixed**
by this feature; repository-wide Python static checks remain red.

### Environment skips and existing findings

Four core tests skip locally:

- `test_branding_assets.py::test_symlink_escape_is_not_previewed`: Windows
  symlink privilege unavailable.
- `test_media_processor.py::test_video_transcoded_to_h264_aac` and
  `test_media_processor.py::test_video_mov_accepted`: local `ffmpeg` executable unavailable.
- `test_package_editor.py::test_artifact_symlink_escape_is_unavailable_and_rejected`:
  WinError 1314, Windows symlink privilege unavailable.

The **new production-renderer tests do execute**, via a Docker subprocess
transport, and do not skip. Browser tests execute installed Chromium using
Playwright 1.63.0. Test media is synthetic; no dojo media or credentials are used.
Port 3000 belongs to another project, so local browser verification uses 3100;
CI defaults to 3000. Browser fixtures route only root `/api/` paths, not Vite's
`/src/api/` modules. API requests are mocked in browser tests; backend seam tests
independently verify authorization and actual FileResponse ranges.

Desktop/mobile visual and keyboard inspection completed in one batch;
confirmation bounded to one additional batch. No horizontal overflow observed.
Impeccable detector ran once: one advisory on the pre-existing onboarding consent
border in `styles.css`; no feature security/privacy/critical accessibility finding.
`npm install` reports 4 existing dependency audit findings (3 moderate, 1 high);
no unrelated forced dependency upgrade was performed.

## Scope and integration

No push, merge, publication, or issue closure performed. This does not implement
the separate web review/publishing flows tracked by #30/#35.
Whole-branch independent review and any verified corrections are recorded below
before integration is offered.
