# Issue #24 design: OpenAPI contract, generated clients, versioning

Goal: one FastAPI-generated OpenAPI contract drives Kotlin and TypeScript
clients; CI fails on drift; backend serves N and N-1 Android releases;
minimum version is public; outdated Android clients get an update prompt.

Decisions (approved):
- FastAPI is the single contract source. `backend/openapi.json` is committed.
- Lightweight Python generator emits TS (`web/src/api/openapi.ts`) and
  Kotlin (`android/.../api/GeneratedApi.kt`) from `openapi.json`. No
  openapi-generator Java dependency.
- CI regenerates all three artifacts and fails on `git diff`.
- Compatibility endpoint: `GET /api/compat` (public, unauthenticated,
  version-gate exempt). Returns `api_version`, `android_min_version_code`,
  `android_current_version_code`, `update_url`.
- Enforcement: middleware checks `X-Android-Version-Code` on `/api/*`
  requests carrying a `Bearer` device credential. Missing/invalid/below-min
  yields `426` with `update_url`. Browser session-cookie requests are never
  version-gated. `/api/compat`, `/health`, `/ready`, Meta OAuth callback are
  exempt.
- Version policy: `ANDROID_CURRENT_VERSION_CODE` (default 1),
  `ANDROID_MIN_VERSION_CODE` (default `max(1, current-1)`, i.e. N and N-1),
  `ANDROID_UPDATE_URL` (configurable HTTPS URL of latest signed APK).
- Android: `MainActivity` fetches `/api/compat` on launch; when
  `VERSION_CODE < min`, shows a blocking update screen with an update button.
  All API calls send `X-Android-Version-Code`.
- Web: banner prompts reload when generated `CONTRACT_VERSION` differs from
  the server's `api_version`.
- Tests: contract freshness is covered by CI diff; backend tests cover
  compat payload, N/N-1 acceptance, below-min 426, missing-header 426,
  browser exemption, and health/compat exemption.
