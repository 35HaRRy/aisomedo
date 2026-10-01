# Issue #26 — onboarding verification

Date: 2026-10-01. Branch: `feat/issue-26-onboarding`.

## Outcome

Guided setup, manual Instagram token entry, OAuth selection, displayed-version
consent, plan/logo/caption/cards configuration, and resumable routing implemented.
Independent whole-branch review completed; three Important findings fixed with
RED→GREEN tests. Acceptance remains qualified by environment limitations below.

## Automated evidence

| Command | Result |
| --- | --- |
| `uv run --project dojo-core pytest dojo-core/tests -q -rs` | 583 passed, 3 skipped |
| `uv run --project backend pytest backend/tests -q` | 129 passed |
| `uv run --project worker pytest worker/tests -q` | 140 passed |
| `npm test` in `web` | 70 passed |
| `npm run typecheck` and `npm run build` in `web` | passed |
| Backend/worker mypy | passed: 22/4 source files |
| Core mypy | existing `publishing.py` dict-item error, now line 441 |
| Python ruff across packages | existing E501 failures; added imports corrected |
| Contract generation and generated-file diff | no drift |

Baseline lint/type failures were reproduced from `d851150` in a disposable
archive. Existing npm audit reports four vulnerabilities (three moderate, one
high); dependency remediation was not part of this change.

PostgreSQL tests ran against disposable Testcontainers databases, including
serialized policy/acceptance concurrency. `test_two_clients_observe_saved_configuration_and_versioned_consent`
pairs two clients against an isolated FastAPI/in-memory installation: client one
saves a disabled plan, uploaded logo, caption, and v1 consent; client two observes
ready state and inherited timestamp. Committing v2 makes readiness false and
rejects stale v1 acceptance with 409.

Scheduling tests prove disabled plans emit no regular slots, unaccepted policies
block schedule evaluation and render-completion review emission, completed renders
remain reusable after readiness returns, and manual one-off reviews remain possible
with regular scheduling disabled. Production worker wires the readiness facade.

## Browser evidence

Playwright exercised the real web app with deterministic intercepted API fixtures.
Fixture: [issue-26-browser-fixture.js](issue-26-browser-fixture.js), invoked with
Playwright's code runner against the development server at port 5176.

- 320px, 390px, 1280px: no horizontal overflow.
- Keyboard navigation through token rejection/success, disabled plan, stale policy
  409 and renewed acknowledgement, logo, caption, optional skip, and finish.
- File chooser populated programmatically; this is not proof of OS chooser keyboard
  accessibility. OAuth candidate selection and reload/reopen also exercised.
- Stale setup read displays alert and recovers on foreground refresh.
- Other-device change preserves dirty caption and offers explicit server reload.
- Protected 401 restores pairing; localStorage + sessionStorage entries: zero.
- No JavaScript page exceptions. Intentional 422/409/500/401 responses produce
  expected browser network error messages.

Screenshots: [320px](issue-26-320.png), [390px](issue-26-390.png),
[1280px](issue-26-1280.png). Token fields captured empty.

## Review fixes

1. Shared review-emission boundary now checks readiness and filters disabled/invalid
   regular plans, including queued render completion. Concurrency race fixture
   explicitly configures its enabled plan rather than depending on missing settings.
2. PNG chunk bounds, CRCs, and complete terminal IEND are checked before decoding;
   tail-truncation and terminal-checksum regressions pass.
3. Logo/card draft fingerprints include asset references; asset-only foreground
   changes now offer reload without overwriting dirty selections.
4. Browser verification found missing stale-progress alert inside wizard; regression
   failed first, then passed after alert was added.

## Remaining verification limitations

- Host FFmpeg unavailable: `test_media_processor.py` tests at lines 113 and 142
  skipped. These checks remain unverified; they are not counted as passes.
- Windows symlink privilege unavailable: branding symlink-preview test skipped.
- Real Instagram token verification/OAuth not exercised; fixture/provider adapter
  tests are not a live integration claim. No production credentials requested.
- Two-client API acceptance used an isolated in-memory installation, not a deployed
  two-browser PostgreSQL stack. Separate PostgreSQL adapter tests passed.

## Deferred minor review findings

- Cards: valid file then rejected replacement leaves prior queued file selected.
- OAuth polling 401 relies on shared setup/status pollers for session invalidation.
- `refresh_due` status copy suggests reconnection despite backend readiness; connection
  method is not displayed.
- Some new Turkish copy remains inline rather than centralized in the catalog.

## Execution decisions

- Read isolated filesystem instead of ambiguous original-checkout codegraph paths;
  cost: additional reads, no behavior change.
- Shared `forms.tsx` owns draft reload, image preview and mutation cancellation;
  cost: helper changes affect three forms, each covered by integration tests.
- Added missing scheduling readiness wiring to satisfy approved spec; standalone
  publishing facades retain optional setup injection for existing callers. Cost:
  callers outside production worker must inject setup to enforce readiness.

No push, PR, merge, or issue closure performed. Environment blockers mean this is
not an unqualified all-checks-green acceptance claim.
