# Issue #25: Web shell, dashboard, pairing, and live updates

## Status and intent

Conversational design approved by the user. This written specification awaits
review before implementation planning.

Issue: https://github.com/35HaRRy/aisomedo/issues/25
Parent: `docs/specs/dojo-reel-publishing-mvp.md`.

Dojo administrators need a paired browser to show authoritative publishing status
and the next action without refreshing manually. Success means a responsive,
Turkish-first shell with four navigation areas, working browser pairing, all five
dashboard status categories, and automatic refresh after worker or other-client
changes. The user explicitly accepted a five-second refresh interval.

## Existing foundations

- React 18, TypeScript, and Vite already exist under `web/`; `App.tsx` is a placeholder.
- Pairing validates one-time codes and issues HttpOnly browser cookies.
  `/api/pairing/me` restores and verifies the session.
- Package, review, plan, activity, and Instagram APIs already exist.
- Generated client artifacts and an existing contract-mismatch banner come from #24.
- Worker health already uses atomic progress records with boot identity and fixed
  idle/busy deadlines. Its default record is currently container-local.
- Issues #3 and #24 are closed.

## Architecture and alternatives

Use a typed, authenticated `GET /api/dashboard` snapshot and visibility-aware
five-second polling. This keeps schedule calculations and business state in the
backend and reduces independent requests for each dashboard section.

SSE would reduce latency but introduces persistent connection and reconnect
handling that the accepted delay does not require. Fetching each existing endpoint
independently would multiply requests and spread dashboard interpretation across
the browser. The snapshot approach is selected.

The endpoint is a read model, not a scheduler trigger. Reads must not create
packages, occurrences, reviews, render jobs, or audit entries. Domain facts are
accessed through public domain interfaces, not route-level private-field access.
The response reflects persisted state; it does not claim a transactionally atomic
view across filesystem, database, and worker-health sources.

## Browser shell and destinations

- Dashboard: active package, next `Yayın Zamanı`, pending action, Instagram health,
  worker health, and refresh status.
- Current Package: read-only package summary with an explicit empty state and
  current pending-review summary when present.
- Activity: a bounded recent-activity summary using the existing API.
- Settings: paired-browser identity and read-only connection/schedule summaries.

Use hash-based navigation so links, browser back/forward, and refresh work without
requiring server-side route fallback. Dashboard is the default destination.
Desktop navigation and compact mobile navigation expose the same four areas.
Pending-review links navigate to its summary, without implying approval has occurred.
Rich upload, review-resolution, and settings-editing workflows belong to their
existing follow-up tickets (#26–#31).

Use semantic headings, keyboard-operable navigation, visible focus, labelled
fields, text alongside status colors, and layouts usable at 320px width.

## Pairing and session lifecycle

On application start, check `/api/pairing/me`. Show a neutral loading state until
authentication is known. A 401 opens a pairing form with code and browser name;
submit to `/api/pairing/validate` with `kind: browser`, then recheck the session.
Credentials remain in HttpOnly cookies; browser storage does not hold tokens.

Invalid/expired codes, throttling, and network failure have separate localized
messages. Disable duplicate submissions. A protected request returning 401 clears
protected UI and cached data, cancels polling, and returns to pairing. Network or
server errors do not masquerade as an expired session.

## Dashboard data

The typed response includes generation time and these groups:

- Current package: identifier, folder/display name, creation time, and lifecycle
  status; explicitly represent no package and publication in progress.
- Next slot: earliest applicable future unresolved regular/manual/rescheduled
  publication time, or null. Compute using existing backend scheduling rules and
  persisted exceptions. An overdue unresolved action appears in pending actions,
  rather than being mislabeled as a future slot.
- Pending actions: current pending-review identifiers, versions, due times, and
  state needed to distinguish review-ready, empty-package, and preparation states.
  Resolved reviews disappear on refresh; multiple pending records are not hidden.
- Instagram: connection health and safe account display information. Missing
  configuration is an explicit disconnected state; no tokens or raw provider errors.
- Worker: healthy idle/busy, unhealthy, or unknown. API readiness is not worker health.

Unavailable optional health information must not hide package/review information.
Return stable machine codes and safe typed fields; localize human-readable UI copy
in the browser. Dates display in `Europe/Istanbul` using Turkish formatting.
Regenerate OpenAPI and both committed client artifacts for contract changes;
generate browser-consumed types from schema rather than maintaining duplicate DTOs.

## Worker-health bridge

Make the existing progress record visible through a dedicated runtime volume:
worker mounts it writable and backend mounts it read-only. Configure a shared
record path with `WORKER_HEALTH_PATH`; retain standalone development support.
Share record validation through a small common utility rather than making the
backend depend on worker process implementation.

Preserve same-boot validation, finite timestamps, and fixed busy deadlines:
idle expires after 120 seconds and busy after 3600 seconds by default. Missing,
corrupt, stopped, wrong-boot, or expired records cannot be reported healthy.
Missing/unconfigured records display unknown; invalid/stopped/expired records
display unhealthy. No Docker socket access is required. Deployment wiring and
worker/container probe behavior must agree on the configured path.

## Refresh and failure behavior

Fetch immediately after authentication. While visible and online, schedule refresh
every five seconds; never overlap requests. Refresh immediately on focus,
visibility restoration, and reconnect, coalescing simultaneous triggers.
Abort obsolete requests and ignore responses from older session generations.

Hide/cleanup cancels timers; reconnect performs a fresh read. Due reviews and
other-device actions appear on the next successful refresh, normally within five
seconds plus request latency after persistence. Worker scheduling latency is
separate from browser refresh latency.

Keep last-known data after transient failure but label it stale/offline and show
last successful refresh time. Before first success, show an explicit error/retry
state rather than fabricated status. Refresh the visible summary destination as
well as dashboard facts so navigation does not leave stale activity or settings.

## Localization

All authored user-facing strings live in a Turkish locale catalog, including
pairing validation, loading/empty/error states, accessibility labels, status labels,
navigation, and the existing compatibility banner. Raw backend errors are not UI
copy. User-provided names and content are displayed as data. The locale interface
permits later translations; no language picker is required for this issue.

## Verification

- Backend/domain behavior: authenticated snapshot, read-only semantics, absent
  package, publishing state, future recurring/manual/rescheduled slots, overdue
  reviews, missing Instagram configuration, and partial health failure.
- Worker bridge: fresh idle/busy records, exact expiry boundaries, stopped,
  corrupt, missing, wrong-boot records, and shared-volume configuration.
- Browser behavior: session restoration, successful/invalid/expired/throttled
  pairing, network failure, revocation, navigation, and Turkish visible strings.
- Deterministic timer tests: due-review arrival, other-device resolution, visibility
  pause/resume, reconnect, no overlapping fetches, stale response rejection, and
  transient-error recovery without discarding last-known data.
- Responsive browser checks at mobile and desktop widths, keyboard navigation,
  and absence of horizontal overflow.
- Typecheck, production build, focused backend/worker tests, and existing generated
  contract drift checks. Tests assert observable behavior rather than internal
  component structure or private method call order.
