# Android shell, dashboard, pairing, and onboarding — issue #32

Date: 2026-10-04
Parent: #1, Dojo Reel Publishing MVP
Prerequisites: #3 and #24 are closed.
Status: written specification approved by user on 2026-10-05; implementation-plan review pending.

## Intent and scope

Give dojo administrators a Turkish-first native Android entry point to the
existing publishing system, without user accounts. Success means a device can
pair once, reopen its authenticated dashboard, complete required setup, and
navigate four distinct areas on phones and tablets.

The user approved a Kotlin/Jetpack Compose shell, one API transport,
backend-derived state, secure persistent pairing, resumable onboarding, and
preservation of the compatibility gate. Android 10 is the minimum version.
Keep business rules in the backend and use CONTEXT.md domain terminology.

Package editing/upload, publication review actions, notifications, offline
caching, and full activity/settings management remain #33–#38. Do not build
their workflows or imply that an unavailable control already works.

## Architecture and dependencies

Replace the compatibility-only Activity UI with a ComponentActivity hosting
Compose Material 3. Use a lifecycle-owned ViewModel and observable screen
state; collect state using lifecycle-aware Compose APIs. Construct dependencies
directly. No DI framework, custom navigation framework, offline database, or
new backend service.

Keep four explicit destinations and a separate onboarding step state. Preserve
destination and non-secret form state across rotation. System Back returns
from onboarding to its owning screen, from a non-dashboard destination to
Dashboard, and otherwise follows the platform exit behavior. Back never
silently saves or accepts anything.

One concrete API client handles JSON requests and branding image transfers.
Use a maintained HTTP implementation supporting PATCH, timeouts, cancellation,
and redirect control; prefer one transport dependency over custom protocol
workarounds. Use Kotlin serialization for generated DTOs. Compose, lifecycle,
serialization, HTTP, and their test support are the only new dependency roles.
Exact compatible versions are pinned in the implementation plan.

Extend backend/scripts/generate_clients.py for the consumed Kotlin schema
closure, not an unrelated all-endpoint SDK rewrite. Generated models preserve
required fields, nullable values, arrays, defaults, and JSON field names.
Reject unsupported schema shapes instead of silently emitting incorrect types.
Keep CompatInfo and UpdatePolicy source compatibility. Ignore unknown additive
response fields; malformed required fields remain errors.
Partial branding requests send only edited keys; preserve omitted-versus-null
semantics so saving a caption never clears an existing logo or cards. Explicit
card removal sends null for the corresponding asset and duration.

## Server configuration and credential boundary

The pairing screen accepts a server base address, client name, and one-time
code. Persist the normalized server address independently of credentials.
Validate a plain origin: no user info, query, fragment, or arbitrary base path.
Require HTTPS in release builds. Local development HTTP is debug-only; the
existing emulator address remains a debug default, not a production URL.
Do not disable certificate verification or follow credential-bearing redirects.
Changing servers clears the old authenticated state before another request.

Device credentials are encrypted with an Android Keystore-backed AES-GCM key
and stored in application-private, backup-excluded storage, bound to the
normalized server origin. Never save plaintext tokens or pairing codes in
preferences, saved-instance state, logs, URLs, or screenshots. Exclude credential
material from both legacy backup and modern data-extraction rules. Lost keys or
unreadable encrypted state return to pairing with a safe explanation.

All authenticated requests and authenticated image previews carry Bearer
credentials and X-Android-Version-Code. Disable automatic replay of pairing
and mutations. A lost pairing response may require a new one-time code; never
pretend an exhausted code can be safely retried automatically.

## Startup, pairing, and compatibility

1. Load server configuration and encrypted credentials. With no server configured,
   show address entry before making requests; validate compatibility after the
   address is submitted and before attempting code validation.
2. Fetch public GET /api/compat. Unsupported installations see only the
   blocking update screen. Open only a valid HTTPS update URL through Android.
3. With no credential, show pairing. Submit POST /api/pairing/validate with
   kind=device, the supplied name, and code. Reject a success response without
   a nonempty device token; persist it before entering authenticated screens.
4. With a credential, GET /api/pairing/me validates identity. Then load setup
   and dashboard. An already-ready installation opens Dashboard.
5. Incomplete setup opens the first unfinished required step once per
   authenticated session. Users may leave onboarding; refresh must not trap
   them in a redirect loop. Settings and Dashboard offer an explicit return.

Compatibility failure shows a retryable connection error and a change-server
action, not invented compatibility or health. A later authenticated HTTP 426
also blocks all mutations and navigation to working screens, without deleting credentials.
Authenticated HTTP 401 clears credentials, pending work, and sensitive UI,
then returns to pairing. A 401 from code validation instead means invalid or
expired code. HTTP 429 has a distinct retry-later message.

Cancellation and a session generation guard prevent a response from the old
server/client from replacing the new session. Rotation does not submit twice.
Never turn cancellation into a generic visible network failure.

## Four navigation areas

- **Dashboard:** show Aktif Paket identity/status or an explicit empty state,
  next Yayın Zamanı or no-slot state, every pending action and its backend state,
  Instagram identity/health, worker health/phase, and setup readiness. Show the
  last successful fetch time when retained in-memory data becomes stale.
- **Aktif Paket:** show the current package identity/status from the dashboard
  projection. Do not create a package merely by visiting this screen. No upload,
  montage, render, or destructive controls in #32.
- **Activity:** a separately navigable explanatory shell; full feed and filters
  belong to #38. Do not label a placeholder as a successfully loaded empty feed.
- **Settings:** show server/current device information, compatibility context,
  setup readiness, and reopen-onboarding action. General settings and paired
  client administration remain #38. Server changes require explicit confirmation
  that this device will need pairing again.

Pending review status is informational here; review resolution belongs to #36.
Dashboard refreshes on explicit retry/refresh and foreground return. No
background worker, notification registration, or live socket is required.

## Resumable guided onboarding

Display all seven checklist items in backend order. Localized labels derive
from known keys, with a safe fallback for future keys. Backend complete and
required flags and ready are authoritative; local navigation does not mark
anything complete. Users may revisit saved steps and navigate back without
losing already-persisted configuration.

1. **Pairing:** show current authenticated device and completion. No second
   account/sign-in flow.
2. **Instagram:** show safe connection status. Support masked manual token
   submission through POST /api/meta/instagram/token and browser OAuth through
   POST /api/meta/oauth/start. Open the returned HTTPS authorization URL via an
   external browser without sharing the device credential. Use no custom return
   URI or callback/deep-link implementation in this ticket. On foreground return,
   or explicit check, fetch the known client-bound attempt and present explicit
   candidate selection before POST /api/meta/oauth/attempts/{id}/select. Preserve
   only the non-secret attempt ID across recreation. Expired/failed/unknown
   attempts offer retry. Never select the first account silently.
3. **Dojo Yayın Planı:** save a Monday anchor date, local time, and enabled flag
   with PUT /api/settings/plan. Show biweekly cadence and Europe/Istanbul.
   A valid disabled plan still counts as configured; enabling never bypasses
   backend readiness. Native date/time controls or Material components suffice.
4. **Consent:** load and display the complete current policy as plain text,
   version, and acceptance timestamp. Require an initially unchecked
   acknowledgement and explicit POST /api/setup/consent/accept carrying the
   displayed version. Existing installation-wide acceptance is inherited.
   On 409 reload the policy and clear acknowledgement, never auto-accept.
   Also clear acknowledgement whenever a refresh changes the displayed version.
   Missing policy is a blocked step with a configure-policy explanation/retry.
5. **Logo:** choose PNG/JPEG through Android's document picker, upload the bytes
   to POST /api/settings/branding/assets, then PATCH the returned server asset
   reference into branding. Load previews through the authenticated transport.
6. **Caption template:** save nonempty opaque text through a partial branding
   update. Do not invent replacement-field interpolation.
7. **Optional cards:** configure intro/outro images and positive finite durations
   through the same upload/partial-update flow, or explicitly POST
   /api/setup/cards/skip. Clearing a card also clears its duration. Optional cards
   never block required readiness, but the wizard presents configure/skip before
   its final summary.

Re-read GET /api/setup after saves. Finish opens Dashboard only after the backend
reports required readiness; leaving setup early is allowed with incomplete
status visible. Save failures retain the step and non-secret inputs. An upload
success followed by a failed branding PATCH retains the returned asset reference
for retry, without claiming the setting was saved. No active-package upload API
is used for branding and no student-media storage permission is required.

Reject branding files larger than 10 MiB while reading, including providers with
unknown size. Backend content/dimension validation remains authoritative. Close
streams and handle cancelled picks, inaccessible URIs, and upload failures.
Uploads are explicit foreground operations; resumable media upload belongs to #33.

Manual Instagram tokens stay only in transient memory, not saved state, and are
cleared after an attempted submission, on leaving the step, and on backgrounding
the app. Never display raw provider responses. Failed reconnect preserves prior
server configuration. Keep dirty non-secret fields on foreground refresh rather
than replacing user edits; indicate changed remote state and offer reload.

## Endpoint and contract changes

Reuse existing pairing/me, dashboard, setup, consent, plan, branding, branding
asset, and Meta operations. No domain-rule or database changes are required.

The current pairing validation and compatibility responses lack explicit typed
OpenAPI output schemas. Add schema metadata describing their existing wire
responses so generated Kotlin types are actually contract-derived. Pairing
describes client_id, kind, and the device-only token; browser cookie handling and
browser token omission remain unchanged. Do not route raw secrets through a
browser response or change legacy JSON keys. Describe the manual-token request
schema without replacing its sanitizing validation with secret-echoing errors.

Regenerate backend/openapi.json, Kotlin models, and TypeScript artifacts with the
existing scripts. Keep byte-deterministic generation and CI drift enforcement.
Additive metadata does not require increasing the minimum Android version.

## Native presentation and accessibility

Use Material 3 components and semantic color/type roles in light/dark themes.
Compact windows use four-item bottom navigation; windows at least 600 dp wide
use a navigation rail, independent of device labels or forced orientation.
Tablet dashboard uses wider/two-column groups; forms retain a readable maximum
width. Recompute layout when windows resize or enter split-screen.

Pending actions lead Dashboard, followed by package/slot and health. Onboarding
uses a step heading, progress/checklist, focused form, and clear save/continue
controls. Health and readiness always have text labels, not color alone.

Handle system/keyboard insets and native Back. Provide 48 dp targets, TalkBack
labels and selection semantics, scrollable content, scalable text, and announced
errors/progress. Disable duplicate submissions without hiding useful content.
Externalize all client-authored visible text, errors, status labels, and content
descriptions in res/values/strings.xml with Turkish defaults. Server-owned policy
text, usernames, and identifiers are content, not client translation keys.

## Verification and acceptance mapping

- Kotlin unit/transport tests: generated DTO decoding, deterministic schema
  generation, authenticated headers, origin validation, safe status mapping,
  stale-session suppression, and required/optional onboarding transitions.
- Credential tests on Android: encrypted persistence/reload, wrong/lost key,
  origin binding, and absence of plaintext credentials in storage/backup paths.
- Compose UI tests with deterministic injected HTTP fixtures: four navigation
  areas; phone/tablet variants; pairing success/reopen/invalid code/revocation;
  dashboard normal/empty/failure; onboarding resume and manual-token clearing;
  OAuth candidate choice; stale consent reset/inherited acceptance; saved logo,
  schedule, caption and optional-card skip; save failure and update-required gate.
- Contract/backend tests: metadata matches existing device/browser response
  behavior, browser tokens remain absent, token errors remain sanitized, and
  regenerated client artifacts stay fresh. Run existing pairing/compat tests.
- Build/check: Android debug assembly, local unit tests, Android lint, contract
  generation/drift checks, and relevant backend tests. Add Android build/unit
  verification to CI if absent; broader distribution/emulator CI remains #39.
- Device evidence: phone and tablet emulator/device screenshots, dark theme,
  1.3 font scale, keyboard and Back behavior. Record unavailable emulator/device
  checks explicitly rather than substituting browser screenshots or claiming
  unexecuted tests passed. Restore any verification-only device settings.

Each of #32's four acceptance criteria maps to these checks. Real Instagram
credentials are not necessary for automated verification; real provider success
is a separately documented manual check, not simulated production evidence.

## Sources checked during design

- Issue #32, parent #1, docs/specs/dojo-reel-publishing-mvp.md, and CONTEXT.md.
- Existing Android activity/build/manifest and backend route/generator source.
- Official Android Compose docs fetched through Context7: navigation bar,
  navigation rail, adaptive apps, state hoisting, and state saving.
- Native Android design guidance: Material 3, window-size navigation, insets,
  accessibility, and emulator/device-only screenshot evidence.
