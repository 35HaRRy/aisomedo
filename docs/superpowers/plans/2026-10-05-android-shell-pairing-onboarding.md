# Android Shell, Pairing, and Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement issue #32: trusted-device pairing, four native navigation areas, status dashboard, and resumable first-run setup.

**Architecture:** Compose Material 3 renders lifecycle-owned state from one AppViewModel. One concrete HTTP client consumes generated Kotlin DTOs; one encrypted SessionStore owns server/credential persistence. Existing backend facades remain authoritative; no DI framework, navigation framework, database, or new backend business rules.

**Tech Stack:** Existing Kotlin 2.0.20, AGP 8.13.2, compile/target SDK 35, min SDK 29; Compose, Android lifecycle, Kotlin serialization, OkHttp, Android Keystore; pytest and Android/JVM tests.

**Spec:** `docs/superpowers/specs/2026-10-04-android-shell-pairing-onboarding-design.md` (user approved 2026-10-05).

## Global Constraints

- Android 10 is the minimum version; preserve minSdk=29 and existing versionCode=1.
- Turkish defaults in `res/values/strings.xml`; use CONTEXT.md domain terminology.
- Release servers and external authorization/update URLs require HTTPS; development HTTP is debug-only.
- Android Keystore-backed AES-GCM credentials, origin binding, backup exclusion; no plaintext persistence/logging/saved state.
- All authenticated requests and previews carry Bearer credentials and X-Android-Version-Code.
- Unsupported clients remain blocked; 426 does not delete credentials, authenticated 401 does.
- Preserve required/default/nullable contract semantics and omitted-versus-null branding PATCH semantics.
- Backend checklist complete/required/ready fields own progress; no local completion database.
- Navigation rail at window widths at least 600 dp; compact windows use four-item bottom navigation.
- Branding images: PNG/JPEG, maximum 10 MiB (10 * 1024 * 1024 bytes); server validates content/dimensions.
- Touch targets at least 48 dp; keyboard/system insets, Back, light/dark, TalkBack, scalable text.
- #33–#38 own package editing, review actions, notifications, offline caching, and full activity/settings; no misleading working controls for those features.
- No implementation before plan review and execution-method selection. Worktree isolation is decided at execution time with using-git-worktrees.

## Review Focus

1. Server origins containing credentials, paths, query/fragment, or redirects: reject without sending a device secret; Task 2.
2. A late response after switching server or revocation: never repopulate the previous session; Task 3.
3. Missing required JSON fields versus explicitly nullable/defaulted fields: fail malformed responses without rejecting valid empty state; Task 1/2.
4. Unknown-size image streams and failed upload-to-settings handoff: enforce byte limit and retain retryable asset reference without claiming a save; Task 7.
5. Consent changes during refresh and dirty-form rotation: reset acknowledgement only when policy changes, preserve safe unsaved edits, never auto-accept; Task 5.

## File and interface map

Existing Android package: `android/app/src/main/java/com/dojo/aisomedo/`.

- `MainActivity.kt`: ComponentActivity, concrete dependency construction, lifecycle/platform adapters.
- `AppViewModel.kt`: AppUiState, startup/session guards, destination/step navigation, backend actions. Secrets remain private, not in AppUiState or SavedStateHandle.
- `api/ApiConfig.kt`: normalized-origin validation and existing version-header helper.
- `api/GeneratedApi.kt`: generated serializable wire models; never hand-edit.
- `api/DojoApi.kt`: concrete cancellable OkHttp transport and endpoint methods.
- `auth/SessionStore.kt`: origin settings, encrypted token file, Android Keystore key helper.
- `ui/DojoApp.kt`: Material theme, startup/pairing/update states, adaptive shell and Back.
- `ui/DashboardScreen.kt`: dashboard and read-only Aktif Paket presentation.
- `onboarding/OnboardingScreen.kt`: checklist/progress, safe drafts, schedule/consent/caption steps.
- `onboarding/InstagramStep.kt`: masked transient token, external OAuth and explicit account selection.
- `onboarding/BrandingSteps.kt`: picker, logo/card upload/preview and optional skip.

All Kotlin test paths below use the same `com/dojo/aisomedo` package tree. Test helpers stay in tests; do not add production interfaces solely for mocking.

### Task 1: Typed contract and runnable Kotlin model tests

**Files:**
- Modify: `backend/src/backend/routes/pairing.py`, `backend/src/backend/routes/compat.py`, `backend/src/backend/routes/meta.py`, `backend/scripts/generate_clients.py`.
- Modify: `backend/tests/test_contract.py`, `backend/tests/test_client_generation.py`.
- Regenerate: `backend/openapi.json`, `web/src/api/openapi.ts`, `android/app/src/main/java/com/dojo/aisomedo/api/GeneratedApi.kt`.
- Modify: `android/build.gradle.kts`, `android/app/build.gradle.kts`.
- Create: `android/app/src/test/java/com/dojo/aisomedo/api/GeneratedApiTest.kt`.

**Interfaces:**
- Produces Python `kotlin_models(schema: dict, roots: list[str]) -> str` alongside existing typescript_models.
- Produces serializable CompatInfo, PairingOut, ValidateIn, ClientOut, DashboardOut, SetupOut, ConsentOut, AcceptanceIn/Out, PlanIn/Out, BrandingDefaultsOut, BrandingAssetOut, StatusOut, StartIn/Out, AttemptOut, SelectIn and referenced types.
- JSON names stay unchanged; Kotlin properties use camelCase with @SerialName. Existing CompatInfo constructor and UpdatePolicy.isOutdated(Int, Int) remain usable.
- PairingOut properties: clientId: Int, kind: String, token: String? = null. Public compatibility response schema is named CompatInfo.

- [ ] **1. Add failing contract/generator tests.** Assert compatibility response has a named schema; pairing schema describes client_id/kind/token while browser wire response omits token. Assert manual-token request documents access_token and malformed input never appears in error text. Use existing backend test app helpers.

```python
def test_kotlin_preserves_required_null_and_defaults():
    schema = {"components": {"schemas": {"Root": {
        "type": "object", "required": ["value"], "properties": {
            "value": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "required": {"type": "boolean", "default": True},
        },
    }}}}
    output = generator().kotlin_models(schema, ["Root"])
    assert "val value: String?" in output
    assert "val value: String? = null" not in output
    assert "val required: Boolean = true" in output
```

Also assert sorted repeatable generation, referenced arrays/scalars, serial names, and ValueError for unsupported non-nullable unions/allOf. Generate only consumed roots; enums with string wire values remain Strings with documented allowed values so future statuses can use UI fallback.

- [ ] **2. Run red.** `uv run --project backend pytest backend/tests/test_contract.py backend/tests/test_client_generation.py backend/tests/test_meta_token_api.py -q`; new assertions fail for absent schemas/generator, not broken fixtures.
- [ ] **3. Implement schema metadata and generator.** Describe existing pairing JSONResponse output without changing cookies/token omission. Add compatibility response_model. Add manual-token requestBody metadata without replacing sanitizing runtime validation. Scalar mapping: integer Int, number Double, string/date/time String, boolean Boolean; nullable anyOf adds `?`, optional fields use schema defaults or null. Reject unsupported shapes. Preserve existing TS generation.
- [ ] **4. Pin only required build dependencies.** Add Compose/serialization plugins version 2.0.20; buildFeatures compose/buildConfig; Compose BOM 2024.10.01 (UI 1.7.5, Material 3 1.3.1), activity-compose 1.9.3, lifecycle runtime-compose/viewmodel-compose/viewmodel-savedstate 2.8.7, coroutines-android/test 1.9.0, serialization-json 1.7.3, OkHttp/MockWebServer 4.12.0, JUnit 4.13.2, Android test runner 1.6.2, test-ext JUnit 1.2.1, Espresso core 3.6.1. Apply BOM to test configurations and add Compose ui-test-junit4/ui-test-manifest; set testInstrumentationRunner to androidx.test.runner.AndroidJUnitRunner. Remove appcompat when replacing its theme in Task 4; do not upgrade existing toolchain as a side effect.
- [ ] **5. Add Kotlin decoding test and run red.** With Json(ignoreUnknownKeys=true, explicitNulls=true), missing DashboardOut.package fails; explicit null succeeds; SetupItemOut.required omitted decodes true; unknown extra property is tolerated; CompatInfo fields decode camelCase correctly. Run `./android/gradlew.bat -p android :app:testDebugUnitTest --tests "*GeneratedApiTest"` on Windows.
- [ ] **6. Regenerate and run green.** Run export_openapi.py then generate_clients.py with `uv run --project backend python`; repeat generation and compare bytes in generator tests. Run the commands from steps 2/5 and `./android/gradlew.bat -p android :app:assembleDebug`. Resolve compile/dependency errors here, without weakening required-field tests.
- [ ] **7. Commit scoped changes.** `feat(android): generate typed shell contracts`.

### Task 2: Origin-bound credential store and safe HTTP transport

**Files:**
- Modify: `android/app/src/main/java/com/dojo/aisomedo/api/ApiConfig.kt`, `android/app/src/main/AndroidManifest.xml`.
- Create: `android/app/src/main/java/com/dojo/aisomedo/api/DojoApi.kt`, `android/app/src/main/java/com/dojo/aisomedo/auth/SessionStore.kt`.
- Create: `android/app/src/debug/AndroidManifest.xml`, `android/app/src/main/res/xml/backup_rules.xml`, `android/app/src/main/res/xml/data_extraction_rules.xml`.
- Create: `android/app/src/test/java/com/dojo/aisomedo/api/DojoApiTest.kt`, `android/app/src/test/java/com/dojo/aisomedo/auth/SessionStoreTest.kt`.
- Create: `android/app/src/androidTest/java/com/dojo/aisomedo/auth/SessionStoreAndroidTest.kt`.

**Interfaces:**
- ApiConfig.normalizeOrigin(raw: String, allowHttp: Boolean): String; require a host, root-only path, no credentials/query/fragment; normalize scheme/host/default port/trailing slash. HTTPS required unless allowHttp.
- SessionStore(directory: File, keyProvider: () -> SecretKey); origin: String? getter, setOrigin(String), readToken(String): String?, saveToken(String, String), clearToken(). Changing origin clears credentials. keyProvider defaults are supplied by Activity, not by tests.
- androidKeystoreKey(alias: String = "dojo-device-token"): SecretKey, and CredentialUnavailable exception with no secret-bearing message.
- DojoApi(origin: String, token: String?, versionCode: Int, http: OkHttpClient): concrete client. suspend request(method: String, path: String, body: JsonElement? = null): JsonElement; suspending endpoint wrappers return generated DTOs. suspend uploadBranding(bytes: ByteArray): BrandingAssetOut; suspend preview(path: String): ByteArray.
- All endpoint wrappers are suspending: compat(): CompatInfo; pair(code: String, name: String): PairingOut (always kind=device); me(): ClientOut; dashboard(): DashboardOut; setup(): SetupOut; consent(): ConsentOut; acceptConsent(version: Int): AcceptanceOut; plan(): PlanOut; savePlan(body: PlanIn): PlanOut; branding(): BrandingDefaultsOut; patchBranding(changes: JsonObject): BrandingDefaultsOut; skipCards(): SetupOut; instagram(): StatusOut; connectInstagramToken(token: String): StatusOut; startOAuth(): StartOut; oauthAttempt(id: String): AttemptOut; selectAccount(attemptId: String, igUserId: String): StatusOut.
- ApiFailure(status: Int, updateUrl: String? = null): Exception; status=0 means connectivity. Do not retain raw error body/detail in exceptions.

- [ ] **1. Write failing store/origin tests.** `rejects_secret_bearing_or_non_origin_urls`: reject `https://user:pass@example.com`, paths, query, fragment, malformed ports, and release HTTP; accept normalized HTTPS and debug emulator HTTP. `encrypted_token_roundtrip_and_wrong_origin`: decrypt only for original normalized origin, file bytes exclude secret, origin change clears token. `wrong_key_or_truncated_file_never_returns_token`: fail closed with CredentialUnavailable; key failure before save does not report successful pairing. Use JCE-generated test key and a temporary directory, not an Android fake interface.
- [ ] **2. Run red.** `./android/gradlew.bat -p android :app:testDebugUnitTest --tests "*SessionStoreTest" --tests "*DojoApiTest"`; missing implementations/new assertions fail.
- [ ] **3. Implement store and URL validation.** AES/GCM/NoPadding, fresh random IV per save, normalized origin as AAD, atomic replacement of private file. Pass context.noBackupFilesDir from Activity; add explicit backup/extraction exclusions and INTERNET permission. Main manifest denies cleartext; debug overlay allows it. Production key comes from AndroidKeyStore; never persist key bytes or log failed payloads.
- [ ] **4. Add failing MockWebServer transport tests.** `headers_patch_and_secret_free_errors`: me/preview carry both headers, public compatibility/pairing carry no Bearer, caption-only PATCH contains only caption_template, clear-card PATCH contains explicit null asset/duration. `redirect_and_cancel_do_not_replay_secrets`: 302 is not followed; cancellation cancels call and remains CancellationException; no automatic retry on POST. `malformed_required_json_fails`: successful-but-invalid dashboard never becomes empty success. Preview rejects absolute/cross-origin paths.
- [ ] **5. Implement transport and wrappers.** Disable redirects, SSL redirects, retryOnConnectionFailure; use finite 10-second connect/read and 30-second call timeout. Bridge OkHttp callback with cancellable coroutines; close responses. Only resolve same-origin `/api/` paths. JSON configuration matches Task 1. Use JsonObject for edited-field PATCH and inline manual access_token body; do not serialize null defaults over untouched settings. Add wrappers for all spec-listed endpoints; body builders covered by wire assertions.
- [ ] **6. Run green and real-key check.** Repeat JVM tests. Android test calls androidKeystoreKey with unique test alias, writes/reads encrypted token, deletes only that alias, then verifies failure. Run `./android/gradlew.bat -p android :app:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=com.dojo.aisomedo.auth.SessionStoreAndroidTest` on a connected emulator; record unavailable devices as blocked, not passed.
- [ ] **7. Commit.** `feat(android): secure device session transport`.

### Task 3: Lifecycle-owned pairing and compatibility state

**Files:**
- Create: `android/app/src/main/java/com/dojo/aisomedo/AppViewModel.kt`.
- Modify: `android/app/src/main/java/com/dojo/aisomedo/MainActivity.kt`.
- Create: `android/app/src/test/java/com/dojo/aisomedo/AppViewModelTest.kt`.

**Interfaces:**
- AppViewModel(store: SessionStore, http: OkHttpClient, versionCode: Int, allowHttp: Boolean, saved: SavedStateHandle): ViewModel; val state: StateFlow<AppUiState>.
- AppUiState includes phase (ADDRESS, LOADING, PAIRING, READY, UPDATE_REQUIRED, CONNECTION_ERROR), origin, client: ClientOut?, compat: CompatInfo?, dashboard: DashboardOut?, setup: SetupOut?, destination: Destination, step: String?, busy, stale, issue: UiIssue?, and onboarding data added in Tasks 5–7. Never include token/code/manual Instagram token.
- Destination enum DASHBOARD, PACKAGE, ACTIVITY, SETTINGS. UiIssue enum for INVALID_SERVER, NETWORK, INVALID_CODE, RATE_LIMIT, INVALID_INPUT, PROVIDER_UNAVAILABLE, POLICY_MISSING, POLICY_CHANGED, STORAGE, UNKNOWN; UI translates, never shows raw error detail.
- Commands: submitOrigin(String), pair(code: String, name: String), refresh(), changeServer(), navigate(Destination), openSetup(), closeSetup(), selectStep(String). Void methods launch lifecycle-owned jobs; no raw Activity thread.

- [ ] **1. Add failing session tests using real SessionStore/test key and MockWebServer.** `no_origin_requires_address_without_network`; `compatibility_before_pairing`; `pair_saves_then_validates_me`; `ready_installation_opens_dashboard`; `incomplete_setup_opens_once`; `invalid_code_does_not_clear_another_session`; `authenticated_401_clears_store`; `426_blocks_but_retains_store`; `late_old_server_response_is_ignored`; `store_failure_does_not_enter_ready`. Assert nonempty device token/kind and safe state with missing/malformed token. Coroutines tests control Dispatchers.Main and restore it.
- [ ] **2. Run red.** `./android/gradlew.bat -p android :app:testDebugUnitTest --tests "*AppViewModelTest"`.
- [ ] **3. Implement startup/commands.** Read origin before requesting compatibility; offer retry/change-server when it fails. Persist token before navigating; validate me then fetch setup/dashboard. A monotonically increasing session generation plus cancelled jobs prevents old results/saves after server changes/revocation. Keep token private and clear sensitive UI on authenticated 401. Gate 426 even if update URL is malformed; only expose validated HTTPS links. Block duplicate pair/saves.
- [ ] **4. Preserve non-secret navigation through SavedStateHandle.** Destination/step survive recreation; incomplete setup redirects only once per live authenticated session. Store safe draft fields later, never credentials/code. Activity constructs store/client/ViewModel directly, passes installed versionCode, and forwards foreground refresh; Compose collection lands in Task 4.
- [ ] **5. Run green plus all existing JVM tests.** `./android/gradlew.bat -p android :app:testDebugUnitTest :app:assembleDebug`; fixture tests must assert request order and no stale session resurrection.
- [ ] **6. Commit.** `feat(android): add pairing and startup state`.

### Task 4: Four-area adaptive shell and truthful dashboard

**Files:**
- Create: `android/app/src/main/java/com/dojo/aisomedo/ui/DojoApp.kt`, `android/app/src/main/java/com/dojo/aisomedo/ui/DashboardScreen.kt`.
- Modify: `android/app/src/main/java/com/dojo/aisomedo/MainActivity.kt`, `android/app/src/main/res/values/strings.xml`, `android/app/src/main/AndroidManifest.xml`, `android/app/build.gradle.kts`.
- Create: `android/app/src/androidTest/java/com/dojo/aisomedo/ui/DojoAppTest.kt`.

**Interfaces:**
- DojoApp(model: AppViewModel, openUrl: (String) -> Unit): composable; DojoTheme(content: @Composable () -> Unit). Activity supplies the external HTTPS Intent adapter; tests supply a recording callback. Failed launch yields safe UI feedback, never an uncaught ActivityNotFoundException.
- DashboardScreen(dashboard: DashboardOut?, setup: SetupOut?, stale: Boolean, wide: Boolean, onRefresh: () -> Unit, onSetup: () -> Unit): composable.
- UI callbacks use Task 3 commands; Material components consume observable state, not network clients.

- [ ] **1. Write failing Compose tests with createComposeRule and concrete fixture ViewModel.** `four_destinations_and_back`; `599dp_bar_600dp_rail`; `dashboard_empty_is_not_load_failure`; `dashboard_renders_all_pending_states_and_health`; `426_hides_mutations`; `settings_server_change_requires_confirmation`. Assert no package-create POST on opening PACKAGE. Use test tags only where labels/semantics are insufficient.
- [ ] **2. Run red on available emulator.** `./android/gradlew.bat -p android :app:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=com.dojo.aisomedo.ui.DojoAppTest`. Without emulator, compile instrumentation tests but leave execution outstanding.
- [ ] **3. Implement native shell and startup screens.** collectAsStateWithLifecycle, window-width-driven rail/bar, Material top bar, system/IME insets and BackHandler. Pairing has labelled origin/name/code inputs and disabled duplicate submission; code uses remember, not rememberSaveable. Use system light/dark Material roles; build vectors/system icons, no image dependency. Replace AppCompat theme with platform no-action-bar theme and remove appcompat dependency.
- [ ] **4. Implement presentation.** Pending actions first; package/slot and health groups follow, two-column grouping when wide. Format timestamps for Turkish in Europe/Istanbul; unknown states get externalized fallback. PACKAGE stays read-only; ACTIVITY explicitly explains later functionality; SETTINGS shows origin/client/version/readiness and setup/server actions. Connection errors retain stale in-memory data only when current session is still valid.
- [ ] **5. Run green and lint.** Repeat UI class command; `./android/gradlew.bat -p android :app:testDebugUnitTest :app:assembleDebug :app:lintDebug`. Fix raw visible text, clipped content, 48 dp targets, and missing accessibility semantics.
- [ ] **6. Commit.** `feat(android): add adaptive dashboard shell`.

### Task 5: Resumable schedule, consent, and caption onboarding

**Files:**
- Create: `android/app/src/main/java/com/dojo/aisomedo/onboarding/OnboardingScreen.kt`.
- Modify: `android/app/src/main/java/com/dojo/aisomedo/AppViewModel.kt`, `android/app/src/main/java/com/dojo/aisomedo/ui/DojoApp.kt`, `android/app/src/main/res/values/strings.xml`.
- Extend: `android/app/src/test/java/com/dojo/aisomedo/AppViewModelTest.kt`.
- Create: `android/app/src/androidTest/java/com/dojo/aisomedo/onboarding/OnboardingTest.kt`.

**Interfaces:**
- AppUiState adds plan: PlanOut?, branding: BrandingDefaultsOut?, consent: ConsentOut?, instagram: StatusOut?, attempt: AttemptOut?, dirtySteps: Set<String>, changedSteps: Set<String>.
- Commands: savePlan(anchorDate: String, anchorTime: String, enabled: Boolean), acceptConsent(displayedVersion: Int), saveCaption(text: String), markDirty(step: String), reloadStep(step: String), finishSetup().
- OnboardingScreen(model: AppViewModel, openUrl: (String) -> Unit): composable; forward platform URL adapter to InstagramStep. Exact backend step keys: pairing, instagram, schedule, consent, logo, caption_template, cards. Safe drafts persist in SavedStateHandle; acknowledgement is associated with displayed consent version and is never submitted automatically.

- [ ] **1. Write failing tests.** `resume_first_required_step_from_backend`; `completed_steps_remain_revisitable`; `disabled_valid_monday_plan_is_configured`; `caption_patch_preserves_other_defaults`; `inherited_acceptance_needs_no_second_post`; `changed_policy_clears_acknowledgement`; `409_reloads_without_accepting`; `missing_policy_blocks_with_retry`; `dirty_rotation_and_remote_refresh_preserve_input`; `ready_does_not_skip_optional_cards`; `failed_save_does_not_advance`. Assert plan PUT body has Monday date/local time/enabled and consent POST version equals displayed version.
- [ ] **2. Run red.** JVM AppViewModelTest command and instrumentation OnboardingTest class command as in Tasks 3/4.
- [ ] **3. Implement progress and core steps.** Fetch setup plus configuration when opening wizard. Backend order/required flags govern progress, with pairing identity as completed informational step. Use Android DatePickerDialog/TimePickerDialog, Monday validation via java.time, nonempty caption, plain-text full policy, unchecked explicit acknowledgement. Save through existing endpoints; re-read setup after success. Missing policy/provider sections fail independently instead of hiding all seven checklist items.
- [ ] **4. Implement refresh and finish semantics.** Preserve dirty safe drafts on refresh and flag remote changes; explicit reload resets affected draft. Policy-version changes always reset consent acknowledgement even on dirty step. 409 reloads without repeat acceptance; failed save stays put. Readiness does not auto-close wizard; present optional cards then final summary. Finish checks backend ready, while close/back may leave incomplete setup.
- [ ] **5. Run green.** JVM tests, OnboardingTest, assembleDebug, lintDebug. UI tests check actual unchecked checkbox/text across recreation, not only ViewModel helper values.
- [ ] **6. Commit.** `feat(android): add resumable setup and consent`.

### Task 6: Instagram token and external-browser OAuth step

**Files:**
- Create: `android/app/src/main/java/com/dojo/aisomedo/onboarding/InstagramStep.kt`.
- Modify: `android/app/src/main/java/com/dojo/aisomedo/AppViewModel.kt`, `android/app/src/main/java/com/dojo/aisomedo/MainActivity.kt`, `android/app/src/main/java/com/dojo/aisomedo/onboarding/OnboardingScreen.kt`, `android/app/src/main/res/values/strings.xml`.
- Extend: `android/app/src/test/java/com/dojo/aisomedo/AppViewModelTest.kt`, `android/app/src/androidTest/java/com/dojo/aisomedo/onboarding/OnboardingTest.kt`.

**Interfaces:**
- Commands: connectInstagramToken(token: String), startOAuth(openUrl: (String) -> Unit), checkOAuth(), selectAccount(igUserId: String). startOAuth invokes callback once after a generation-checked success; do not launch the browser from a replayable state-flow effect.
- InstagramStep(model: AppViewModel, openUrl: (String) -> Unit): composable; token is unsaved remember state, not part of observable app state. OAuth StartOut.authUrl and known attempt ID drive platform browser launch/check.

- [ ] **1. Write failing tests.** `manual_token_clears_on_attempt_leave_and_background`; `provider_error_does_not_display_token_or_raw_payload`; `oauth_start_never_sends_device_secret_to_browser`; `return_to_foreground_checks_known_attempt`; `multiple_candidates_require_choice`; `failed_expired_unknown_attempt_allows_restart`; `rejected_reconnect_keeps_prior_status`. Assert token request uses correct endpoint, one explicit candidate selection, and no hard-coded custom callback/deep link.
- [ ] **2. Run red.** AppViewModelTest and OnboardingTest commands.
- [ ] **3. Implement safe token connection.** Mask input, clear on any attempted submit/step exit/background, including failure; validate nonblank <=16384 chars without echo. Preserve previous displayed connection until verified replacement. Map 422/provider outage to externalized safe errors.
- [ ] **4. Implement OAuth.** POST start with no custom return_uri; validate HTTPS before Intent.ACTION_VIEW. Catch unavailable browser. Preserve non-secret attempt ID, check on foreground/explicit action, show candidate picker, only select on tap. No background polling/notifications or callback interception. Handle ready/selected/pending/expired/failed/unknown status according to actual backend wire fixtures, with safe fallback.
- [ ] **5. Run green.** Unit/UI commands and lint; assert SavedStateHandle/store files contain no manual token. Rotation clears secret input without losing safe fields/attempt ID.
- [ ] **6. Commit.** `feat(android): add Instagram setup step`.

### Task 7: Branding uploads, authenticated previews, and optional cards

**Files:**
- Create: `android/app/src/main/java/com/dojo/aisomedo/onboarding/BrandingSteps.kt`.
- Modify: `android/app/src/main/java/com/dojo/aisomedo/AppViewModel.kt`, `android/app/src/main/java/com/dojo/aisomedo/onboarding/OnboardingScreen.kt`, `android/app/src/main/res/values/strings.xml`.
- Extend: `android/app/src/test/java/com/dojo/aisomedo/api/DojoApiTest.kt`, `android/app/src/androidTest/java/com/dojo/aisomedo/onboarding/OnboardingTest.kt`.

**Interfaces:**
- BrandingSteps.kt readBrandingImage(input: InputStream): ByteArray enforces 10 MiB before unbounded allocation; Android URI open/MIME checks use ContentResolver and picker.
- Commands: uploadAsset(field: String, bytes: ByteArray), retryAsset(field: String), saveCards(introAsset: String?, introDuration: Double?, outroAsset: String?, outroDuration: Double?), skipCards(). field whitelist: logo_asset, intro_asset, outro_asset. retryAsset installs the retained uploaded reference without repeating the upload.
- AppUiState adds pendingAssets: Map<String, BrandingAssetOut>; retained uploaded reference supports retry after PATCH failure. Previews load via DojoApi.preview with scoped credentials, not public URLs or image-library networking.

- [ ] **1. Write failing stream/wire/UI tests.** `unknown_size_stream_stops_at_limit_plus_one`: exact 10 MiB allowed, 10 MiB+1 rejected and stream closed by owner. `cancelled_or_unreadable_picker_preserves_branding`; `upload_then_patch_failure_retains_reference_for_retry`; `previews_require_headers_and_same_origin`; `clear_card_sends_asset_and_duration_null`; `invalid_nan_zero_duration_not_sent`; `explicit_skip_reloads_setup`; `optional_cards_then_finish_ready`. No package media endpoints may appear in request history.
- [ ] **2. Run red.** DojoApiTest/AppViewModelTest and OnboardingTest commands. Use synthetic bounded streams; no student media or real Instagram credentials.
- [ ] **3. Implement picker and upload handoff.** ActivityResultContracts.OpenDocument for image/png/image/jpeg; no broad storage permission. Read/close off main thread, cap actual bytes regardless of advertised size; validate image with backend. Keep returned asset before PATCH, show failure separately, retry same reference without re-upload. Only advance after backend settings save/setup reload.
- [ ] **4. Implement card configure/clear/skip and preview.** Explicit positive finite durations, preserve untouched defaults, authenticated bounded image decode, content descriptions. Prevent concurrent duplicate uploads. Optional cards configure/skip remains available after required ready; final summary reflects separate readiness/card status.
- [ ] **5. Run green.** Unit tests, full OnboardingTest, assembleDebug/lintDebug; verify picker URI cancellation/error on Android and stream byte boundaries in tests.
- [ ] **6. Commit.** `feat(android): add logo and optional card setup`.

### Task 8: Integration verification, CI, and user guide

**Files:**
- Modify: `.github/workflows/ci.yml`.
- Create: `docs/verification/issue-32-android-shell.md`, `docs/rehberler/issue-32-android-kabuk-deneme-rehberi.md`.
- Extend existing Kotlin/UI/backend tests for any discovered integration gap; no unrelated refactoring.

**Interfaces:**
- Consumes complete Tasks 1–7, existing OpenAPI drift check, Android Gradle wrapper.
- Produces recorded command/device evidence and runnable Android build/unit/lint CI; no signed release or broad emulator CI rollout (#39).

- [ ] **1. Add final failing integration cases.** Assert rotation/reopen does not pair twice, revoked credentials stop wizard mutation, current 426 overrides any onboarding step, no server means no network, and tablet resize changes navigation without losing draft. Confirm each acceptance criterion has an executed check or explicit blocked item.
- [ ] **2. Run red before fixes.** Full JVM/UI suites; capture specific failures, then fix only uncovered integration defects. Do not weaken tests or infer screenshot success from APK assembly.
- [ ] **3. Add Android CI job.** Ubuntu checkout, Java setup compatible with repository daemon criteria (Java 25), Android SDK setup/license acceptance, existing Gradle wrapper from android directory; run `./gradlew :app:testDebugUnitTest :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest`. Existing contract job stays intact. Validate YAML and keep CI free of localhost/production credentials. Do not alter Gradle daemon/vendor criteria merely to fit CI.
- [ ] **4. Run complete verification.** Windows commands below are from repo root; Unix uses `./android/gradlew -p android` instead of .bat.

```powershell
./android/gradlew.bat -p android :app:testDebugUnitTest :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest
./android/gradlew.bat -p android :app:connectedDebugAndroidTest
uv run --project backend pytest backend/tests/test_api.py backend/tests/test_contract.py backend/tests/test_client_generation.py backend/tests/test_onboarding_api.py backend/tests/test_meta_token_api.py backend/tests/test_branding_assets_api.py -q
uv run --project backend ruff check backend/src/backend/routes/pairing.py backend/src/backend/routes/compat.py backend/src/backend/routes/meta.py backend/scripts/generate_clients.py backend/tests/test_contract.py backend/tests/test_client_generation.py
uv run --project backend mypy backend/src/backend
uv run --project backend python backend/scripts/export_openapi.py
uv run --project backend python backend/scripts/generate_clients.py
git diff --exit-code -- backend/openapi.json web/src/api/openapi.ts android/app/src/main/java/com/dojo/aisomedo/api/GeneratedApi.kt
```

For drift comparison, first commit intended generated outputs with Task 1 or corresponding schema fix; never stage stale artifacts just to silence a mismatch. Also run `npm test` and `npm run build` with workdir web after regenerated TS changes.

- [ ] **5. Inspect native evidence in one batched pass.** Phone/tablet light and dark, font scale 1.3, consent scroll, keyboard/insets and Back, empty/error/update states. Capture with adb on emulator/device into `.impeccable/review/`; use a binary-safe shell/process for screenshot output on Windows, not Windows PowerShell text redirection. Restore font scale/theme. Fix observed defects as one batch, confirm at most once; use native guidance, not HTML detector. Record unavailable device/provider checks honestly. Finish review follows chosen execution workflow; never spawn agents before user chooses a method.
- [ ] **6. Write Turkish manual guide and evidence.** Include server entry, bootstrap code generation, debug emulator address, HTTPS physical-device pairing, full setup flow, reopen/revocation/426, APK install, executed commands/device classes, known deferred tickets. No secrets or real personal media. Manual provider success is labelled separate from deterministic fixtures.
- [ ] **7. Commit.** `test(android): verify shell and onboarding`.

## Plan self-review and handoff

- [x] Spec coverage: contract (1), origin/credentials/transport (2), startup/revocation/compat/session (3), native shell/dashboard (4), core setup/dirty refresh/consent (5), Instagram (6), branding/cards (7), CI/device evidence/accessibility (8).
- [x] Step scan: each task has named assertions, red/green commands, concrete files/interfaces, and commit boundary; no speculative SDK/module layer.
- [x] Type consistency: generated DTO camelCase names, string checklist keys, shared commands and state fields agree across tasks.
- [x] Review Focus: all five failure classes have named owning-task tests.
- [x] Proportion: plan records decisions and tests, not implementation function bodies.
- [ ] User reviews plan and chooses Native or Subagent-driven execution.

Recommendation: Native. Tasks deliberately share a small number of interfaces/files and run sequentially; one final independent review preserves scrutiny without paying fresh implementer/reviewer context for every slice.

Documentation consulted: official Android Compose compiler/BOM setup and Compose testing docs via Context7. Compose BOM artifact 2024.10.01 was fetched from Google's Maven repository (Material 3 1.3.1/UI 1.7.5); serialization-json 1.7.3 artifact exists. Dependency resolution/build remains an execution check, not a claimed planning-stage pass.
