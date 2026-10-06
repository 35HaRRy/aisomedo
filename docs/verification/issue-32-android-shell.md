# Issue #32 — Android shell verification

Date: 2026-10-05. Branch: `feat/issue-32-android`; baseline: `d9e941f`.

## Implemented scope

Native Kotlin/Compose four-area shell; origin selection; encrypted origin-bound
device session; compatibility/426 gate; dashboard; backend-driven resumable
pairing/Instagram/schedule/consent/logo/caption/cards setup. No accounts, DI or
navigation framework, offline database, package creation on screen entry,
package editor, review actions, notification registration or full activity feed.

User guide: [Turkish step-by-step trials](../rehberler/issue-32-android-kabuk-deneme-rehberi.md).
The guide uses Android/browser interactions and PowerShell fallbacks, without
Python or SQL source code. Its 23 PowerShell blocks were parsed successfully;
live infrastructure/provider trial steps were not executed here.

## Executed checks

| Check | Evidence/result |
| --- | --- |
| Backend baseline | 20 compatibility/generation/manual-token tests passed |
| Full backend suite | `uv run --project backend pytest backend/tests -q`: 171 passed; existing Starlette deprecation warning |
| Backend typecheck | `uv run --project backend mypy backend/src/backend`: 23 files, no issues |
| Changed Python lint | Generator, compat/pairing/meta routes, generation and Android-contract tests: Ruff passed |
| Android | 39 JVM tests passed after review fixes; Gradle `:app:testDebugUnitTest :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest` successful locally |
| Web tests | `npm test`: 288 passed in 30 files |
| Web production build | `npm run build`: TypeScript check and Vite build passed |
| Generation | Exported OpenAPI and regenerated clients; final drift check compares intended committed outputs |
| CI configuration | YAML parsed; Android job added; Java launcher 25, unchanged JetBrains daemon criteria, SDK/build-tools 35 |
| Native runtime attempt | `:app:connectedDebugAndroidTest` failed with `No connected devices!`; no AVD installed |

Local Android environment: Windows, Android Studio JBR launcher, repository
Gradle 9.3.0 wrapper, Kotlin 2.0.20, AGP 8.13.2, SDK 35, min SDK 29. Builds emit
Gradle-10 deprecation notices; these are not clean-room Linux CI execution evidence.
The Android instrumentation APK was compiled, not run. No screenshots captured.

## Regression checks and acceptance mapping

| Requirement/failure mode | Runnable check | Status |
| --- | --- | --- |
| Required nullable DTO fields/defaults/additive keys | `GeneratedApiTest`, generator pytest | JVM/Python executed |
| Original compatibility constructor/wire metadata | `GeneratedApiTest`, `test_android_contract.py` | JVM/Python executed |
| Origin validation and encrypted reload/wrong key/corrupt file | `SessionStoreTest` | JVM executed |
| Real Android Keystore key loss | `SessionStoreAndroidTest` | Compiled; device execution blocked |
| Authorization/version headers, redirects, safe errors, cancellation | `DojoApiTest` | JVM executed |
| Compatibility before pairing, save before READY, invalid token/save failure | `AppViewModelTest` | JVM executed |
| Authenticated 401, 426 retention, stale old-server responses | `AppViewModelTest` | JVM executed |
| Preview 401 clears session and blocks wizard writes | `previewRevocationClearsSessionAndBlocksWizardWrites` | RED: READY instead of PAIRING; fix routes preview rejection to shared failure handling |
| Reopen retains safe draft/navigation without pairing again | `reopeningSessionRestoresSafeDraftAndNeverPairsAgain` | JVM executed; actual rotation still manual |
| Four areas/Back, 599/600 dp switch, update gate, server confirmation | `DojoAppTest` | Compiled; device execution blocked |
| All pending states and nonempty/empty distinctions | `DojoAppTest` | Compiled; device execution blocked |
| Actual refresh/reconnect/oneoff status keys | `HealthLabelsTest` | RED unknown-label assertions; specific Turkish labels added |
| Disabled Monday plan and Tuesday rejection | `AppViewModelTest` | JVM executed |
| Partial caption PATCH, dirty refresh/explicit reload, failed-save retention | `AppViewModelTest` | JVM executed |
| Policy change, version-bound acceptance, 409 reload, inherited acceptance, missing policy | `AppViewModelTest` | JVM executed |
| Actual checkbox/reset/text and manual-token clearing | `OnboardingTest` | Compiled; device execution blocked |
| Explicit OAuth candidate choice, no custom return URI, HTTPS callback once, restart | `AppViewModelTest` | JVM executed with synthetic responses |
| Rejected reconnect preserves previous status/no raw secrets in state | `AppViewModelTest` | JVM executed |
| Upload/PATCH failure retains reference; retry without re-upload | `AppViewModelTest` | JVM executed |
| Card clearing sends both nulls; finite positive duration; explicit skip | `AppViewModelTest` | JVM executed |
| Exactly 10 MiB/unknown-size limit-plus-one, stream ownership closes | `BrandingReadTest` | JVM executed |
| Same-origin authenticated bounded previews | `DojoApiTest` | JVM executed |

RED→GREEN logs were retained in this plan's ignored execution workspace during
implementation. Initial task RED phases failed to compile absent commands/DTOs;
integration regressions also failed on concrete behavior assertions before fixes.

## Checks still outstanding

- Real API 29+ phone/tablet run; light/dark, font scale 1.3, TalkBack, 48 dp
  interactions, system/IME insets, policy scroll, rotation/window resize, Back.
- Android document picker cancellation/unreadable URI and previews on device.
- Actual Android Keystore persistence/backup exclusions on device. Files are
  located in `noBackupFilesDir`; backup/data-transfer exclusions are declared.
- Successful live Instagram token verification or live OAuth. Current backend
  OAuth provider is a stub; synthetic candidate fixtures are not live-provider proof.
- New Android GitHub Actions job execution in Linux CI; no push/remote CI run here.
- End-to-end manual guide's Docker/real device flows. Parser/build/test checks do
  not establish that an operator has completed these trials.

These are blocked/unexecuted checks, not silently passing acceptance criteria.
Issue #32 is not closed solely on compilation evidence.

## Independent final review and fix pass

One read-only fresh-context reviewer inspected `d9e941f..765a2cf`. No critical
findings. All five important findings were reproduced and fixed in one pass:

| Finding | Regression and fix evidence |
| --- | --- |
| Preview 426 overwritten by older dashboard refresh | `preview426CannotBeOverwrittenByDelayedDashboard`: RED READY instead of UPDATE_REQUIRED; generation invalidation plus pending-job cancellation now retains update gate/credential |
| Preview 401 left upload continuation alive | `preview401CancelsUploadBeforeReferenceOrPatchCanReturn`: RED old reference restored; cancellation and generation checks before post-await state writes/follow-up requests suppress both reference and PATCH |
| Save erased edits entered after submission | `captionEditMadeAfterSubmissionRemainsUnsavedAndVisible`: RED Submitted replaced new unsaved text; only unchanged submitted draft snapshots are marked clean |
| Save completion reopened a wizard the user left | `leavingWizardDuringSaveDoesNotReopenIt`: RED caption step reopened; advance only while user remains on submitting step without a dirty replacement draft |
| Card clear/duration writes replaced untouched sibling settings | `clearingOneCardDoesNotSendOtherCardCachedValues`, `changingOneDurationDoesNotResendAssetOrUntouchedDuration`, `dirtyIntroDurationDoesNotFreezeOrOverwriteRemoteOutroDuration`: RED excessive PATCH keys/old untouched draft; diff-only card PATCH and per-field edited flags preserve untouched server values |

Guide's disabled `/docs` link was graded Important for this user's runnable
walkthrough: replaced with read-only PowerShell inspection of committed
`backend/openapi.json`. Failing route-reference assertion preceded fix; all
23 PowerShell blocks parse and replacement inspection returned expected schemas.

Final Android suite/build/lint: 39/39 JVM tests passed. No re-review dispatched;
test-first fix pass is the verification. No deferred minor findings remain.
Native runtime/provider/remote CI checks above remain outstanding, not passed.

## Implementation rulings

- Track the copied known Gradle wrapper/daemon files; keep SDK-local settings
  ignored. Wrong choice cost: build packaging repair.
- Compile native tests and report no-device block rather than inventing runtime
  evidence. Wrong choice cost: native defects can escape runtime checks.
- Put additive Android wire assertions in `test_android_contract.py` instead of
  enlarging `test_contract.py`. Wrong choice cost: relocating a test file.
- Reuse transport's bounded reader for branding, avoiding unsupported Java 9
  `InputStream` APIs at min SDK 29. Wrong choice cost: relocating one helper.
- Replace MainActivity together with DojoApp in Task 4 rather than adding
  temporary UI in Task 3. Wrong choice cost: integration one commit later.
- Keep consent acknowledgement transient and keyed by displayed policy; submit
  validates displayed version and clears checkbox immediately. Wrong choice cost:
  consolidating checkbox state into ViewModel.
- Final reviewer declined native rendering/accessibility/picker/Keystore runtime
  judgment. Keep acceptance blocked until device trials; do not close issue on
  compiled tests. Wrong choice cost: undiscovered native behavior defects.
- Final reviewer declined live Meta success judgment. Keep synthetic OAuth and
  live provider evidence separate; stub provider is not upgraded in this ticket.
  Wrong choice cost: live-provider defects need separate integration work.
- Final reviewer declined deferred feature-scope judgment. Preserve #33–#38
  boundaries and truthful placeholders. Wrong choice cost: follow-up tickets are
  required before those Android workflows are usable.

## Deferred feature scope

Android package/upload/edit/review/notification/full activity-settings work stays
in #33–#38; signed distribution/emulator CI rollout stays in #39. No database or
backend business-rule change is part of this issue.
