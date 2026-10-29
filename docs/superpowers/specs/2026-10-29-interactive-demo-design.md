# Interactive Demo Design

## Status and workflow

- [x] Inspect the existing routing, session, API, live updates, and persistence paths.
- [x] Confirm requirements and edge-case decisions with the owner.
- [x] Select existing application screens with an in-memory mock transport.
- [x] Write and self-review this design.
- [x] Owner reviews the written design.
- [x] Write and review the implementation plan; select native execution in the existing checkout.
- [x] Implement and verify the approved plan.

This document is the design deliverable, not an implementation plan. Product code remains unchanged. Documentation is English; questions to the owner remain Turkish.

## Purpose

Let visitors try the real Aisomedo web interface without pairing a real account, reading production data, writing to a database, or contacting external publishing services. Add a **Demo** link beside the existing navigation items in the welcome page header. It opens `/#/demo/dashboard`.

The demo reuses the application screens and workflow: prepare a Paylaşım Paketi, edit media and captions, render a sample result, make a Yayın İncelemesi decision, and inspect simulated Tamamlanmış Paketler and activity. It is an interactive sandbox, not a separate screenshot-based presentation.

## Agreed requirements

1. Demo data reads and writes use a mock API layer. No request may fall through to the real API while demo mode is active.
2. The session represents a fictional, paired user whose setup is complete. The dashboard opens immediately; the setup wizard remains accessible and editable.
3. Every applicable list record type starts with at least two examples. Singleton resources, such as the user profile and settings, have one complete example.
4. Changes exist only in memory. They survive navigation between demo screens and reset on page reload. Leaving and reopening the demo starts a new seed state.
5. Demo routes live beneath `/#/demo/`. The base route resolves to `/#/demo/dashboard`.
6. Display a visible, accessible lowercase **demo** label next to the application logo.
7. A browser with a real pairing marker is redirected to the corresponding non-demo route before real session validation happens.
8. Uploads provide local previews only. Rendering, publishing, and Instagram connection operations simulate results without uploading files, connecting accounts, or publishing anything.
9. Removing pairing inside the demo discards the sandbox and opens `/#/welcome`, without changing real pairing state or cookies.

## Approach and alternatives

**Selected: existing screens with a shared mock transport.** Keep the current typed `api` methods and screen components. Route their operations to an in-memory handler before native network access. Adapt the separate live, compatibility, and browser-managed media paths explicitly. No new dependency is needed.

**Not selected: Service Worker interception.** This can intercept network requests, but introduces installation, control timing, scope, and cleanup concerns for a sandbox that can run entirely in memory.

**Not selected: separate demo screens.** This reduces integration work initially but duplicates the product UI and drifts from actual behavior.

No global replacement of `window.fetch`, fake backend service, generic plugin system, or production database seed is required.

## Existing integration points

- `web/src/promotion/LandingPage.tsx`: welcome header navigation.
- `web/src/App.tsx`: session gate, workspace providers, sidebar logo, links, and the hardcoded onboarding redirect.
- `web/src/session.tsx`: real session restoration currently calls `api.me()` on mount. Demo selection must happen before this effect can issue a real request.
- `web/src/navigation.ts`: hash parsing, query parameters, and unsaved-edit guards. Its current parser does not understand a `demo/` prefix.
- `web/src/api/client.ts`: typed API methods share `request()`, including upload chunk operations.
- `web/src/api/compat.tsx` and generated `web/src/api/openapi.ts`: compatibility checks have a separate fetch path. Adapt the caller or shared transport, not generated contract code by hand.
- `web/src/live.ts` and `web/src/liveProvider.tsx`: live events use a separate fetcher; the workspace is disabled unless its live phase is ready.
- `web/src/packages/usePackageEditor.ts` and `web/src/packages/drafts.ts`: editor recovery uses localStorage and IndexedDB.
- `web/src/uploads/UploadProvider.tsx`: upload controllers receive localStorage and a transport.
- `web/src/promotion/tourProgress.ts`: walkthrough progress is persisted by client ID.
- `web/src/onboarding/InstagramStep.tsx`: authorization opens an external window, independently of the API request.
- Media components and upload conflict controls use browser-managed image/video URLs, including some constructed API URLs. JSON interception alone does not cover these paths.

## Route and mode boundary

Determine mode synchronously from the hash before session restoration, compatibility checks, or live startup. Match the exact demo segment (`#/demo` or `#/demo/…`), not unrelated prefixes such as `#/demonstration`.

| Incoming route | Real pairing marker | Result |
| --- | --- | --- |
| `/#/demo/` | absent | Start demo and normalize to `/#/demo/dashboard` |
| `/#/demo/package?review=7` | absent | Open the demo package screen and preserve the query |
| `/#/demo/package?review=7` | present | Replace with `/#/package?review=7`, then validate the real session |
| `/#/demo/` | present | Replace with `/#/dashboard`, then validate the real session |
| Any normal route | either | Existing normal session behavior |

The pairing marker is a non-secret browser-local hint, not authentication. Set it only after successful real session validation; remove it when normal session handling confirms revocation or a 401. A network error alone must not clear it. Never write the marker from a mock response. Existing browsers without the new marker enter the demo without a real session probe, even if they have an older valid cookie. They obtain the marker on their next successful normal-session validation. This follows the owner's explicit rule: demo prefix plus no marker means mock access only.

If storage is unavailable, treat the marker as absent unless the running application already knows it has a validated real paired session. The marker never grants access; the backend remains authoritative after redirect.

Use mode-aware route parsing and link construction. Preserve review, occurrence, and package-folder query parameters. All internal demo navigation, including sidebar links, setup redirects, walkthrough actions, and Back/Forward transitions, retains the prefix. Preserve existing unsaved-edit guards rather than bypassing them. Unknown demo areas resolve inside the demo dashboard, never to a real route.

On transitions, dispose the previous workspace, abort in-flight reads and simulated work, reset resource-version state, and prevent late results from crossing modes. Do not permit a pending normal-session restore to replace the mock identity. Selecting demo mode must stop an existing real live connection before mounting demo consumers.

## Mock API and state

Place the small demo runtime, seed data, and handlers under `web/src/demo/`. Keep the existing API request/response types. Store state per active demo session rather than reinitializing it on each screen mount.

The shared transport selects the mock before any native fetch call. Demo handlers match HTTP method and path, parse query/body values, validate mutation inputs, and return contract-compatible values or errors. Unknown operations fail explicitly; there is no native-fetch fallback. Preserve abort behavior, error handling, and relevant version/precondition checks used by existing components.

Mutations must affect subsequent reads and related views. For example, editing an active package updates its revision; rendering creates a sample ready preview; simulated review approval updates publication state, completed packages, and activity together. Skip and reschedule remain distinct from confirmed publication. Do not make every write return a generic success response.

Generate mock resource invalidations locally after successful mutations. Integrate them with existing refresh subscriptions so screens re-read mock state and the demo workspace reaches its usable live phase without opening `/api/events`. Compatibility is satisfied locally using the current contract version; no real compatibility request is sent.

Capture the active mode/session generation for every operation. A mock operation must not become a real request if navigation changes during an await, and an old response must not mutate a replacement session.

## Seed data

Use fictional names, account handles, captions, and identifiers; no real tokens, pairing codes, personal media, or production responses. Choose stable IDs and derive date-sensitive timestamps from a seed-session clock so reviews and schedules remain usable over time.

Minimum coverage:

| Resource | Starting examples |
| --- | --- |
| Paired client/profile | One fictional browser client |
| Setup, consent, branding, plan, reminders, connection status | One complete singleton of each |
| Active package | One, matching the application's single-active-package invariant |
| Completed packages | At least two with distinct details |
| Media records | At least two, including photo and video, with usable sample previews |
| Review records | At least two reachable records with coherent package/revision associations |
| Publication occurrences | At least two demonstrating the existing scheduled/manual flows |
| Activity events | At least two different actions |
| Simulated account-selection candidates | At least two fictional accounts |

Populate any additional applicable list-backed domain resource found during implementation with at least two coherent examples. The minimum concerns initial examples, not a lower bound after users delete, clear, or complete records. Do not invent additional active packages, profiles, or settings collections merely to reach two entries. Use existing supported associations for review examples, not impossible duplicate active state.

## Uploads, previews, and external services

Reuse upload UI and input validation, but handle all metadata, chunk, status, completion, and conflict operations in memory. Selected bytes never leave the browser. Keep original user media only as needed for local object-URL previews; release references and revoke URLs when removed or when the sandbox ends.

Serve bundled fictional preview assets from a public demo asset directory. Mock payloads return those static URLs or blob URLs, never real `/api/` media URLs or remote media URLs. Adapt constructed conflict, branding, artifact/download, and render-preview links as well as URLs returned by the API. Native `<img>`, `<video>`, and download requests cannot rely on the JSON mock transport.

Rendering uses clearly identified sample output; it does not pretend the uploaded file was actually transcoded. Publishing changes local simulated state only, and the interface explains that no Instagram post is created. Keep this explanation close to the affected actions, in Turkish, without replacing the product UI.

Instagram authorization completes locally and shows fictional account candidates without calling Meta, opening an external authorization window, or retaining submitted secrets. Demo-specific copy must not claim that a token was sent to a server. Do not require real credentials to explore this flow.

Static application bundles and bundled demo assets may load from the web host. “No real API” prohibits backend/API and external integration requests; it does not prohibit loading the application itself. Ordinary explicit external navigation, such as social links, is not a mock API operation, but simulated workflow actions must never trigger it.

## Persistence and lifecycle

Use memory-only storage for demo upload recovery, editor drafts, clear-operation recovery, and walkthrough progress. Reuse existing storage seams where possible; add only the narrow mode branch needed where persistence is currently hardcoded. Do not use a fake client ID as the only isolation mechanism: demo edits must not write to IndexedDB or localStorage at all.

Reading the non-secret pairing marker is permitted. Normal global theme preferences remain outside demo record state. Do not delete or overwrite real uploads, drafts, tour progress, pairing markers, or cookies during demo startup, mutations, or teardown.

Reset on full reload, leaving the demo, or removing the fictional pairing. Do not reset merely because a component remounts or development StrictMode replays an effect. Navigate between demo areas using one sandbox instance.

Removing the fictional pairing is handled locally before any real revocation path. Dispose demo controllers, subscriptions, object URLs, and state, then open `/#/welcome`. Reopening the demo creates fresh seed data.

## UI and accessibility

Add a real **Demo** anchor alongside welcome header navigation so keyboard activation, link copying, and opening in a new tab work normally. Display **demo** next to the workspace logo at desktop and narrow widths. Do not communicate demo status by color alone.

Keep existing Turkish application labels, form validation, focus handling, loading/error states, and unsaved-edit confirmation. Make simulation notices readable by assistive technology. No unrelated visual redesign is included.

## Failure handling

- Unknown mock method/path: explicit local error; zero real network attempts.
- Invalid mock input or stale package/review version: contract-compatible validation/conflict error, not silent success.
- Cancelled operation or disposed session: abort and ignore late results.
- Unavailable sample asset: visible preview error without a real API retry URL.
- Stale real pairing marker: redirect first; normal authentication handles the invalid cookie and clears the hint on confirmed rejection.

## Verification and acceptance

Use the existing test tooling; no new framework is required.

1. Route tests cover exact prefix matching, base normalization, query preservation, unknown areas, marker/no-marker behavior, and Back/Forward transitions.
2. Session tests prove direct demo startup does not call real `me`, compatibility, live events, or revocation paths. Real paired redirects happen before real validation and do not enter the sandbox.
3. Mock tests verify seed counts, representative mutations, consistent read-after-write state, cancellation, preconditions, and explicit rejection of unknown operations without fetch fallback.
4. Integration tests exercise settings, setup, editing, upload preview, render, review decisions, completed details, and activity using existing screens. Changes survive demo navigation but not reset/reload.
5. Persistence tests preload real localStorage/IndexedDB records and verify demo interactions leave them unchanged, with no demo record writes. Demo pairing removal preserves real state.
6. A browser acceptance check records requests and fails on any `/api/` request or workflow-triggered external request from an unpaired demo. Exercise media previews, conflict previews, downloads, compatibility, and live startup, not only JSON reads. Load static assets normally; do not hide leakage by fulfilling API requests in the browser test.
7. Browser checks confirm the welcome header link, visible demo label, functional narrow layout, local-only Instagram flow, and fresh state after reload/reentry.
8. Existing normal-session, navigation, editor, upload, and live-state checks continue to pass. Type checking and production build remain required.

## Non-goals

- No backend, worker, database, Android, or deployment redesign.
- No real account provisioning, OAuth, uploads, rendering, publication, emails, or notifications.
- No persistent demo sessions, cross-tab synchronization, shareable edited state, or user-selectable scenario system.
- No copied screen hierarchy, Service Worker, new dependency, or generic transport framework.
- No unrelated refactoring or changes to existing user work.

## Implementation notes

- The shared transport lives in `web/src/api/transport.ts`; mock routing, seed state, media handlers, and runtime ownership live in `web/src/demo/`.
- Local live updates reuse the existing SSE coordinator. Ownership cleanup is generation-aware so an old workspace cannot disable a newly opened demo.
- Draft stores bind to their owning sandbox, preventing deferred writes from switching to the real IndexedDB store after exit.
- Browser-held upload chunks supply local previews at completion; the existing upload controller supplies previews before completion. Rendering always uses the bundled, locally generated six-second sample video.
- Saved object URLs retain their MIME types so uploaded video cards remain videos after navigation. Clearing or completing a package invalidates its pending mock reviews; unrelated packages cannot be approved through an old review.
- The real-pairing hint is non-secret and cannot grant authentication. A validated session also retains an in-memory hint when browser storage is unavailable. An older cookie without either hint still enters the demo without probing the real API, as agreed.
- The welcome page mounts no session consumers after demo exit. Opening the normal app performs normal authentication; opening Demo starts fresh seed data.
- Existing visual conventions remain unchanged, including the accent border explicitly pinned by `DESIGN.md`. No new dependency was introduced.

## Verification outcome

- Unit and integration suite: **469 tests passed across 47 files**.
- Full desktop/mobile browser suite: **93 passed, 1 skipped**, including the eight demo acceptance cases.
- TypeScript and production Vite build: passed.
- Diff whitespace check: passed.
- Independent read-only review completed. Live ownership, stale review association, saved-video MIME handling, and validated-session fallback findings were reproduced and fixed with regression tests; the full suites were rerun afterward.
- Changes remain uncommitted in the existing `development` checkout. Preexisting lockfile, workspace configuration, and LinkedIn document changes were preserved.
