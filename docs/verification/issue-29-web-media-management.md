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
| `uv run --project dojo-core pytest dojo-core/tests -q` (after review corrections) | 646 passed, 4 skipped; new real-renderer checks executed |
| `uv run --project backend pytest backend/tests -v` | 155 passed |
| `uv run --project worker pytest worker/tests -v` | 140 passed |
| `npm test` (web, after review corrections) | 233 passed, 28 files; also passed with four workers |
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

## Independent review and correction pass

Detailed future investigation notes for the 11 execution decisions and deferred
Minor: [issue #29 follow-up notes](issue-29-follow-up-notes.md). These are pending
investigations, not completed fixes or an approved new implementation plan.

Read-only reviewer inspected `1fc600d..31fbd38` and reported four Important
findings, no Critical, and one Minor. All four Important findings were reproduced
as failing tests before production changes, then corrected in one pass:

1. Render validation now durably fails the queued job when eligibility changes
   after enqueue; scheduler leaves invalid/over-limit input pending instead of
   enqueueing it. Six regressions cover limits, missing duration, and invalid
   selected ranges. Focused core tests: 19 passed.
2. Section removal resolves the displayed raw-input row rather than the
   independently sorted timeline index, preventing numeric edits from deleting
   the wrong retained section. End-user regression verifies saved content.
3. Follow-up reads exempt only acknowledged order/removal/restoration changes.
   Concurrent unrelated saved selections preserve drafts and mark them stale.
   Three regressions cover reorder/remove/restore.
4. Lost-write reconciliation has an independent read-required lock. Discard can
   clear local edits but cannot unlock writes; an explicit authoritative refresh
   must reconcile committed selections before another aggregate save.

After corrections: core 646 passed / 4 environment skips; web 233 passed;
backend 155 passed; browser desktop/mobile 4 passed; production web
build/typecheck passed. Worker 140 passed in the preceding final verification.

Unrestricted concurrent verification initially had two timing failures:
`App.test.tsx::resumes incomplete setup once and preserves intentional navigation`
(onboarding lookup timeout) and
`PackageManager.test.tsx::completed view uses draft decision and cancel keeps editor mounted`
(decision timeout). Both passed isolated; the cancellation fixture now waits for
its async guard to release. Full suite with `--maxWorkers=4` passed all 233 tests.
Assertions and product timeouts were not weakened. A subsequent default-worker
`npm test` run with no competing browser/Python verification also passed all 233.

### Deferred Minor

`RangeTimeline` rounds after clamping. Non-millisecond duration/neighbor bounds
can produce an invalid draft; validation prevents persistence and exact fields
allow correction. Follow-up: round before final clamp and test fractional bounds.

### Decisions preserved from the execution ledger

Each decision includes its cost if the assessment proves wrong:

1. Allocate unused minute-shaped folder identity at same-minute rollover while
   preserving real `created_at`: stale package guards otherwise cannot work.
   **Cost:** displayed folder timestamp can be slightly ahead of creation.
2. Update the existing signed raw-download assertion to paired same-origin
   delivery, matching the approved privacy design. **Cost:** consumers need paired
   credentials rather than public raw-media links.
3. Permit `PLAYWRIGHT_PORT` override; default 3000 stays, local verification uses
   3100 without disrupting another project. **Cost:** explicit local env override.
4. Do not fix unrelated baseline Python static errors in this feature.
   **Cost:** repository-wide lint/type CI stays blocked until separate cleanup.
5. Reviewer-set-aside baseline static/audit findings remain reported separately,
   based on reproduced baseline evidence. **Cost:** static/dependency risk remains.
6. Leave existing manifest/render coordination races and reverted-input
   failed-digest suppression unchanged; the newly demonstrated draft conflict was
   corrected. **Cost:** existing concurrent render/recovery workflows may still
   need separate repair.
7. Retain Linux symlink tests without claiming Windows execution.
   **Cost:** local platform-specific symlink behavior is not execution-proven.
8. No speculative decimal-keyboard/performance redesign without device/load
   reproduction. **Cost:** decimal entry or many-video archive browsing may be
   inconvenient or slow on untested devices.
9. No legacy sub-frame compatibility rewrite without a demonstrated usable
   rendered-content regression. **Cost:** unusual legacy trim may need re-selection.
10. Explicitly distinguish browser API fixtures from production backend seams;
    no deployed end-to-end proof claimed. **Cost:** deployment integration defect
    might remain undiscovered.
11. Limit simultaneous web verification to four workers during Docker/Python
    load and wait for async cancellation in the test fixture; subsequent default
    run also passed. **Cost:** uncontrolled CI load can still reveal timing flakiness.

Review gate: all demonstrated Critical/Important findings addressed; deferred
Minor and baseline/static/environment limitations remain explicit. No second
review was dispatched; RED→GREEN regressions and full suites verify corrections.
