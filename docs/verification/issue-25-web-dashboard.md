# Issue #25 verification

Branch: `feat/issue-25-web`. Specification and plan are under `docs/superpowers/`.

## Implemented acceptance criteria

- Four responsive navigation areas; dashboard shows package, next slot, pending
  action, Instagram connection, and independently observed worker progress.
- Browser pairing uses existing one-time-code API and HttpOnly cookies.
- Foreground refresh interval is five seconds; focus/reconnect refresh immediately.
- Turkish UI catalog includes loading, errors, status, navigation, and compatibility banner.

Current Package, Activity, and Settings are summary views. Uploads, review approval,
and settings editing remain in subsequent tickets.

## Evidence (2026-10-01)

- Web: 21 behavioral tests pass; TypeScript check and production build pass.
- Backend: full suite, 119 passed.
- Worker: full suite, 140 passed.
- Core: full suite, 360 passed, 4 skipped, 166 fixture errors because Docker's
  `dockerDesktopLinuxEngine` pipe was unavailable. No assertion failures in that run.
  Earlier focused dashboard run included real PostgreSQL: 35 summary/scheduling/
  review tests passed before Docker became unavailable.
- Backend and worker mypy pass with `--no-incremental`. Incremental mypy crashed
  internally. Core non-incremental mypy retains an existing recovery-audit dict
  typing error in `publishing.py`; dashboard/worker-health additions have no errors.
- Regenerated OpenAPI and TypeScript/Kotlin artifacts have no drift.
- Development and both production Compose modes render successfully. Shared
  health file path matches across backend and worker; backend mount is read-only.
- Mechanical UI detector: no findings.

## Browser checks

Used Chromium through Playwright against the built frontend served by a real
FastAPI HTTP app with disposable in-memory domain storage. This is not the full
production Compose/PostgreSQL deployment.

- Pairing via form succeeds; `dojo_session` cookie observed with `httpOnly: true`.
- Long Turkish browser name wraps correctly.
- Worker-triggered due slot appears automatically without manual page refresh.
- A second independent browser context pairs successfully.
- Revoked first browser returns to pairing on the next protected fetch and clears
  package data.
- Dashboard at 1280px, 390px, and 320px has no horizontal overflow; desktop and
  mobile screenshots were inspected.
- Review arrival/resolution, offline/stale recovery, and hash navigation are covered
  by deterministic browser-component tests. Actual two-browser review resolution
  was not completed: the disposable empty-package fixture emitted a due occurrence
  but no review to resolve. Do not count that attempted scenario as passed.

## Reproduction

Run `npm ci`, `npm test`, and `npm run build` under `web/`.
Run full Python suites separately with `uv run --project <package> pytest
<package>/tests -q`, for `dojo-core`, `backend`, and `worker`.
Docker Desktop must be running for PostgreSQL fixtures.

For a deployed browser check, use disposable installation data, pair two browser
contexts with distinct codes, configure consent/branding/media and a due plan,
run the worker, resolve the generated review from one client, and observe its
removal in the other within five seconds plus request latency. Revoke one browser
and verify its protected UI clears. Repeat offline recovery and hash back/reload.

## Remaining gates

- Re-run all core PostgreSQL fixtures with Docker available.
- Complete deployed-stack two-browser review resolution and offline/hash checks.
- Final independent review and any required fixes.
- Do not close issue #25 or claim full deployed acceptance until remaining gates pass.
