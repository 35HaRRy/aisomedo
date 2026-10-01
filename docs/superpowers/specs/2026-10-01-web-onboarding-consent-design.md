# Web guided onboarding and consent — issue #26

Date: 2026-10-01
Parent: #1, Dojo Reel Publishing MVP
Prerequisites: #5 and #25 are closed.
Status: conversational design approved; written-spec review pending.

## Intent and approved scope

Provide a Turkish-first, resumable first-run wizard for dojo administrators.
Users configure Instagram, the Dojo Yayın Planı, consent, logo, caption template,
and optional intro/outro cards directly in the application. Reuse the existing
browser pairing flow rather than implementing another session system.

The user explicitly requires manual entry of an access token obtained from
Instagram. This is a first-class connection option alongside Meta OAuth, not
an operator-only fallback. The backend verifies and stores the credential;
the browser displays only safe connection status after submission.

Success means all seven first-run items are visible, consent acceptance is
recorded for the displayed policy version, and backend state alone determines
whether required setup is complete. Optional cards never prevent readiness.

## Architecture

Add onboarding to the existing web shell, retaining Dashboard, Current Package,
Activity, and Settings navigation. Use a dedicated onboarding hash route and
small step components, the existing session provider, API request helper,
Turkish string catalog, and foreground live-refresh conventions.

Reuse `DojoMetaConnection` for connection work, `DojoPublishing` for plan and
branding configuration, and `DojoSetup` for checklist and consent behavior.
Routes translate HTTP requests; domain decisions belong in these facades.
No separate onboarding service, frontend state library, or completion table.

Extend backend behavior only where this flow requires it: schedule and optional
card tracking, version-checked consent, partial branding updates, and independent
branding image upload. Do not use package-media uploads for setup assets.

## Wizard behavior

1. Pairing: the existing unpaired screen establishes the browser session. The
   wizard then shows pairing as complete and identifies the current client.
2. Instagram: show current account, connection method, and health, with OAuth
   and manual access-token connection controls.
3. Dojo Yayın Planı: configure a Monday anchor date, local time, and enabled
   flag. Display biweekly cadence and `Europe/Istanbul` explicitly.
4. Consent: show the full policy as plain text, version, and existing acceptance
   timestamp. Require an unchecked acknowledgement before explicit acceptance.
5. Logo: upload a branding image and show an authenticated preview.
6. Caption template: save nonempty text. Store it as opaque text; do not invent
   substitution syntax or interpolate unknown replacement fields.
7. Optional cards: configure intro/outro images and durations, or explicitly
   skip. Show their optional status even before they have been reviewed.

On the first successful setup-state load after pairing, incomplete installations
enter onboarding at the first unfinished required step. Do not repeatedly
redirect users who intentionally navigate elsewhere during that session.
Dashboard and Settings remain accessible. Settings exposes a reopen-setup action.
Already-ready installations open the existing dashboard normally.

Each successful save is durable independently. Next/back navigation does not
discard saved configuration; reload reconstructs progress from the backend.
Unsaved field values remain local to the mounted step. Failed saves do not
advance the step. Users may revisit completed steps.

Required readiness may become true before optional cards are reviewed. During
the guided flow, present the card configure/skip choice before the final summary;
do not automatically navigate away when readiness becomes true. Finish returns
to Dashboard. Expose readiness and optional-card status separately.

## Backend-derived checklist and scheduling

Preserve existing checklist keys and add `schedule` and `cards`. Add a
`required` boolean, defaulting to true, to checklist entries; `cards` is false.
Return the full ordered checklist even when Instagram is unavailable, with
Instagram incomplete rather than silently omitted.

- Pairing: at least one non-revoked client, retaining installation-wide behavior.
- Instagram: connection health is `healthy` or `refresh_due`.
- Schedule: valid Monday anchor and local time are configured. Disabled but
  valid plans count as configured; scheduling still obeys the enabled flag.
- Consent: current policy has installation-wide acceptance.
- Logo: nonempty configured asset reference.
- Caption template: nonempty text after whitespace validation.
- Cards: valid configured card settings or an explicit skip decision recorded
  through an authenticated setup action. Existing configured cards count as
  reviewed. Store a skip/review marker in the existing settings store.

`ready` and `DojoSetup.is_ready()` depend only on required entries. Scheduling
continues to require both setup readiness and an enabled, valid plan. A new
unaccepted policy or unhealthy Instagram connection can make readiness false
again. Do not mutate the active package or schedule when opening the wizard.

## Instagram connection and token handling

Manual connection submits `{access_token}` to the existing authenticated
`POST /api/meta/instagram/token`. Use a masked input, explicit submit action,
and Turkish instructions explaining that a valid Instagram credential with
the backend's required permissions is needed. Do not imply arbitrary token
types or accounts are accepted. Show account identity only after verification.

Keep token text only in transient component memory. Never put it in local or
session storage, navigation state, URLs, analytics, error text, or logs. Clear
the input after a submission attempt and on step unmount. Responses and UI
contain only safe account/health data. Preserve backend encryption-at-rest and
sanitized validation errors. A failed reconnect leaves the prior connection
intact. No browser-side calls to Instagram's API or new token-exchange logic.

For OAuth, initiate a client-bound attempt using existing APIs, open the auth
URL in a new window, and poll the known attempt while the application is open.
No new callback return-URI construction is required. Completed attempts show
an explicit account picker; never silently choose the first account. Handle
expired, failed, and unknown attempts with safe retry controls. A blocked popup
offers an explicit open-link action. Cancel polling on unmount or session loss.

## Version-specific consent safety

The web client submits the version it displayed with acceptance. Extend the
acceptance request with optional `version`: new web clients always send it;
legacy callers without a body retain existing current-policy semantics.

For versioned requests, check that the expected policy is still current and
record acceptance within one serialized policy/acceptance transaction. A
different current version produces HTTP 409 without accepting the new policy.
Policy updates participate in the same concurrency boundary. In-memory and
database adapters must preserve this invariant, not only sequential tests.

Repeated acceptance is idempotent: one record and audit event per version,
including accepting client identity and timestamp. New paired clients inherit
installation-wide acceptance. On 409, reload policy and reset acknowledgement;
never auto-accept. On missing policy, show a blocked step with retry and a clear
message that an administrator must configure the policy. Editing policy text
under an already accepted version is outside this issue; version increments
remain the mechanism for requiring renewed consent.

## Branding persistence and image uploads

Keep existing full `PUT /api/settings/branding` behavior compatible. Add a
partial update operation for wizard saves: omitted fields remain unchanged;
explicit null clears an optional field. Validate nonempty captions and positive,
finite card durations when present. Clearing a card also clears its duration.
Missing duration uses the existing photo-duration default. Do not change
existing package manifests, immutable renders, or copied draft defaults when
editing installation-wide settings.

Provide authenticated branding-asset upload and preview endpoints independent
of active packages. Wizard uploads PNG/JPEG raster images only for logo and
cards; existing server-configured asset types continue to work. Limit each new
upload to 10 MiB and decoded dimensions to at most 4096 pixels per side. Reject
unsupported, malformed, oversized, or undecodable images before settings change.
Check actual decoded content, not just supplied MIME type or filename.

Generate immutable, server-owned asset references under the configured media
root; do not accept user filenames as paths or browser-supplied filesystem paths.
Authenticated preview resolves only generated references within that directory.
Upload returns a reference; the subsequent partial settings update installs it.
Failed uploads or saves leave prior defaults intact. Retain replaced files to
preserve existing package references; automatic garbage collection is out of
scope. Use existing render asset resolution for the stored references.

## Data refresh, errors, and accessibility

Reload setup state and affected configuration after saves. Refresh foreground
setup and policy state on the existing live-data cadence, visibility return,
and focus, so other-device changes become visible without manual refresh.
Do not overwrite dirty form values during background refresh. Display changed
state and require an explicit reload of a dirty step where needed.

Do not show stale data as a new successful save. Show recoverable load/save
errors with retry; disable duplicate submissions; cancel outstanding requests
on session changes. HTTP 401 restores the pairing screen. Treat token-provider
outage separately from invalid credentials without displaying provider payloads.

All new user-facing strings live in the Turkish catalog. Reuse the existing
visual language and responsive shell. Provide labelled controls, keyboard
navigation, visible focus, current-step semantics, announced errors/progress,
and focus transfer to the heading when changing steps. No background Web Push.

## API contract compatibility

FastAPI remains the contract source. Regenerate committed OpenAPI, TypeScript,
and Kotlin artifacts for new operations and additive fields. Retain legacy
consent calls and full branding replacement semantics. Do not bump minimum
Android version merely for this additive feature. Test contract freshness.

## Verification

Domain and adapter tests cover required/optional checklist derivation, valid
disabled schedules, whitespace validation, single consent acceptance/audit,
inherited acceptance, concurrent policy changes, and partial branding updates
preserving untouched values and existing package snapshots.

Authenticated backend tests cover versioned and legacy consent requests,
stale-version 409, missing-policy 404, card skip persistence, plan validation,
image upload limits/content/path containment, protected previews, and manual
token success/rejection/provider outage without credential leakage.

Web tests cover the full wizard, pairing transition, resume/reopen, OAuth
candidate selection/retry, manual token submission and clearing, inherited
acceptance, policy-change acknowledgement reset, optional-card skip, Monday
validation, upload/save failures, session expiry, dirty-form preservation, and
foreground other-device updates.

Run frontend tests, typecheck/build, affected backend/domain tests, Python
lint/type checks, and generated-contract freshness checks. Browser verification
covers desktop/mobile layouts and keyboard flow with deterministic API fixtures;
real Instagram credentials are not needed for automated verification.

## Out of scope

Package-media uploads (#27), filename conflict UI (#28), montage editing (#29),
review actions (#30), broad settings/activity expansion (#31), Android onboarding
(#32), policy authoring UI, multi-account publishing, token acquisition from
Instagram, caption interpolation, and branding-file garbage collection.
