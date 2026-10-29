# Aisomedo Product Promotion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a consistent promotion kit, scroll-integrated Turkish landing page, and contextual Turkish web walkthroughs.

**Architecture:** Keep the existing React application, pairing, setup, navigation guards, and publishing behavior. Add a public introduction and browser-local page tours; reuse a small set of captured application images across documentation and promotion. Complete independently verifiable tasks in order; do not create a content-management subsystem.

**Tech Stack:** Existing React 19.3.1, TypeScript, CSS, Vitest, Playwright, PowerShell, Docker Compose, Kotlin Android, and existing operator CLIs. A free/open-source tour dependency may be added only after checking its API, license, and accessibility behavior.

**Spec:** `docs/superpowers/specs/2026-10-28-product-promotion-design.md`

**Execution tracking:** Implemented inline in the existing `development` checkout, without commits. Detailed check results and decisions are retained in `.superpowers/sdd/2026-10-28-product-promotion/progress.md`. Android captures remain blocked by unavailable native device/emulator; the documentation reports this gap rather than substituting web screenshots. The checklist below is the original implementation brief; the ledger records execution and deviations.

## Global Constraints

- Do not commit any changes.
- Preserve existing user changes, including the guide relocation.
- Do not read or reuse Markdown files under `docs/guide/archive-tr/`, or recover their old copies for use as source material.
- English copy uses short sentences and common words. Turkish copy uses plain language and the domain terms from `CONTEXT.md`.
- No measured business results are available. Do not claim percentage improvements, time savings, user counts, publication success rates, or leadership outcomes without evidence.
- All usage instructions and workflow screenshots use the web application.
- Mobile screenshots appear in the final Android section.
- Use PowerShell commands, with no inline Python or SQL code.
- Required setup takes precedence; no promotional overlay competes with consent or the setup wizard.
- Never publish to Instagram, deploy infrastructure, create a release, modify production data, or commit as part of this work.

## Review Focus

- Existing environment and data: quick start must not replace secrets, reset volumes, or start an accidentally configured production publisher (Task 1).
- Expired/revoked pairing and unsaved edits: public navigation must retain deep-link intent and existing leave guards (Task 3).
- Browser storage disabled, corrupt, or shared between clients: tours must degrade safely and retain client isolation (Task 4).
- Missing/moving targets and product dialogs: no stranded overlay, hidden action, or accidental product mutation (Task 5).
- Motion disabled, touch screens, or missing animation APIs: every landing section and tour control must remain reachable (Tasks 3 and 5).

---

## File map and dependency order

1. **Runnable local setup:** `ops/start-local.ps1`, `ops/docker-compose.local.yml`, `ops/tests/start-local.Tests.ps1`.
2. **Shared assets:** `web/e2e/promotion-fixture.ts`, `web/e2e/promotion-capture.spec.ts`, `web/public/promotion/`, `docs/guide/screenshots.md`.
3. **Public introduction:** `web/src/promotion/LandingPage.tsx`, `web/src/promotion/promotion.css`, `web/src/promotion/LandingPage.test.tsx`, `web/e2e/promotion.spec.ts`; integrate through `App.tsx`, `navigation.ts`, and existing tests.
4. **Tour state:** `web/src/promotion/tourProgress.ts`, `web/src/promotion/tourProgress.test.ts`.
5. **Page tours:** `web/src/promotion/Walkthrough.tsx`, `web/src/promotion/tours.ts`, `web/src/promotion/Walkthrough.test.tsx`, `web/e2e/walkthrough.spec.ts`; add small target attributes to existing controls.
6. **Promotion documents:** root `README.md`, `docs/cv.md`, `docs/linkedin.md`, three English guides and `docs/guide/check-promotion.mjs`.

Task 1 is independent of UI work. Tasks 2 and 4 produce inputs for Tasks 3 and 5. Task 6 describes and verifies the final product. If execution is split, use these task boundaries rather than parallel edits to shared application entry points.

## Task 1: Safe PowerShell quick start

**Files:** Create the three setup files in the file map. Reuse existing environment templates and operator CLI entry points without editing `ops/.env`.

**Interfaces:** `ops/start-local.ps1 [-PairingCode] [-CheckOnly]` runs from any working directory, exits nonzero on failure, and prints the local web URL. `-PairingCode` runs the existing pairing CLI in the local backend container; do not implement pairing in PowerShell. `-CheckOnly` validates prerequisites without creating files or services.

- [ ] Inspect production gateway/build configuration, backend CLI syntax, Dockerfiles, and local cookie/origin requirements. Choose a separate `aisomedo-local` Compose project with named volumes and a generated gitignored `ops/.env.local`; never reuse `ops/.env` or production secrets. Generate local secrets with cryptographic .NET APIs, preserve existing local values, and disable scheduling on new installations.
- [ ] Add a runnable PowerShell assertion check in `ops/tests/start-local.Tests.ps1` using disposable paths and mocked external commands, without adding Pester. Assert missing Docker produces nonzero exit; `-CheckOnly` creates nothing; existing environment sentinel bytes are unchanged; failed Compose prevents pairing execution; local commands never reference `ops/.env` or delete volumes. Run `powershell -NoProfile -File ops/tests/start-local.Tests.ps1`; confirm failure before implementing the script.
- [ ] Implement the script and local Compose overlay. The overlay must include schema initialization before backend/worker readiness, avoid host-bind data directories, and serve the built web client and API through one local origin using existing gateway patterns. On new installations, create no Instagram connection or enabled plan. For existing local installations, warn that an enabled configured publisher can act and require explicit confirmation before starting the worker. Fail on native command errors and show actionable prerequisite/port messages. Keep prerequisite installation manual and documented.
- [ ] Rerun the PowerShell checks; require exit 0. Run `docker compose --env-file ops/.env.local -p aisomedo-local -f ops/docker-compose.yml -f ops/docker-compose.local.yml config --quiet` and exercise first startup plus repeat invocation in an isolated local project. Verify health, web access, pairing code generation, and schema initialization; never print generated secrets. If Docker is unavailable, record that runtime verification is blocked rather than claiming startup works.

## Task 2: Shared application captures and visual evidence

**Files:** Create the capture files and asset directory from the map; reuse `web/src/test/fixtures.ts`, `web/e2e/live-fixture.ts`, and media fixtures. Create `docs/guide/screenshots.md`.

**Interfaces:** `installPromotionFixture(page: Page): Promise<void>` serves deterministic non-personal sample states in tests only. Shared asset paths are `/promotion/web/dashboard.png`, `package.png`, `sections.png`, `review.png`, `completed.png`, and `/promotion/android/` captures. Missing captures are blockers, not placeholder images.

- [ ] Write `promotion-capture.spec.ts` asserting real visible headings and loaded media for the five web states, with zero unexpected API requests or page errors. Follow existing appearance-test fixtures but use a single consistent fictional package and identity. Run `npx playwright test e2e/promotion-capture.spec.ts --project=desktop` in `web`; confirm the new scenario fails before its fixture is implemented.
- [ ] Implement the fixture with existing API types and live-stream helper. Add opt-in `CAPTURE_PROMOTION=1` screenshots after fonts/media load and tour suppression is applied. Normal tests must not overwrite assets. Capture actual app-rendered states; do not paint screenshots with custom HTML. Record that these are synthetic demo states, including the completed-package scenario, not live publishing evidence.
- [ ] Run the capture test successfully, then capture with `$env:CAPTURE_PROMOTION='1'` and the same command. Inspect every image for readable content, consistent data, and absence of sensitive data. Include extra setup screens needed by the detailed guide using this same fixture approach.
- [ ] Inspect available Android emulator/device and existing test/demo tooling. Capture at least three real Android views using controlled sample data without adding fake production functionality. Verify signed APK and checksum assets through read-only GitHub release queries; record the exact working release links. If Android capture or releases are unavailable, record explicit blockers and do not silently substitute narrow web views or dead download buttons.
- [ ] Write `screenshots.md` with capture commands, file inventory, capture provenance, fixture limitations, media rights/privacy notes, release evidence, and any blockers. List verified technical capabilities with source references for the later CV; do not label capability numbers as efficiency measurements.

## Task 3: Scroll-integrated landing and safe public routing

**Files:** Create landing files from the map. Modify `web/src/App.tsx`, `web/src/navigation.ts`, `web/src/App.test.tsx`, and affected navigation/appearance tests. Add original SVG artwork under `web/public/promotion/`.

**Interfaces:** `LandingPage({ onOpenApp }: { onOpenApp: () => void }): JSX.Element`. Public hashes `#/welcome` and `#/pair` do not become workspace `Area` values. Section IDs are `intro`, `benefits`, `workflow`, `android`, and `start`; use `data-section` anchors instead of overwriting hash-based application routes. Paired workspace Help links navigate through the existing `navigate()` guard.

- [ ] Load applicable UI design skills before implementation. Add unit/browser tests for unpaired empty-hash introduction, explicit pairing entry, existing protected deep links, paired default dashboard, explicit paired welcome access, and cancelled navigation with dirty edits. Assert successful pairing retains the intended application destination. Run the new tests and observe failure before entry-point changes.
- [ ] Implement public-route selection and `LandingPage` without replacing session/authentication providers or the protected workspace. Visiting `#/welcome` is possible independently of API availability; entering a protected page still uses the existing session/error gate. Preserve destination intent without storing credentials or bypassing existing route guards.
- [ ] Build Turkish hero, benefit cards, workflow story, Android preview, and final entry action. Reuse Task 2 assets and create original SVG icons/artwork. Section buttons scroll into view without changing the application hash. Section navigation exposes the current section with an accessible state.
- [ ] Implement desktop sticky workflow visuals: scrolling through upload, edit, review, and publication steps switches the active screenshot and restrained icon/highlight transitions. Use IntersectionObserver and CSS rather than a new animation dependency. Narrow screens use inline visuals and natural document flow. Reduced motion disables smooth scrolling and decorative transitions. Missing observer support leaves readable complete content.
- [ ] Extend `promotion.spec.ts`: click each section control and assert target visibility without route-hash changes; scroll manually and assert active workflow/section updates; test keyboard links, 390px and desktop layouts, no horizontal overflow, light/dark themes, reduced motion, and absent IntersectionObserver. Assert zero page errors. Run `npm test -- src/promotion/LandingPage.test.tsx src/App.test.tsx` and `npx playwright test e2e/promotion.spec.ts e2e/appearance.spec.ts` from `web`; require pass.

## Task 4: Minimal persisted tour progress

**Files:** Create `tourProgress.ts` and its test file.

**Interfaces:** Export `TourProgress = { version: 1; completed: string[]; dismissed: string[]; skipAll: boolean }`, `readTourProgress(clientId: number): TourProgress`, and `writeTourProgress(clientId: number, progress: TourProgress): void`. Store under `aisomedo:promotion:v1:<clientId>` on the current origin. Catch read/write failures and retain same-session in-memory state. Export `resetTourProgress(clientId: number): void` for explicit Help replay only.

- [ ] Write tests for empty/default state; completed/dismissed ID round trips; skip-all applying to an unseen tour; separate clients; corrupt JSON; incompatible version; invalid field types; localStorage getter/read/write throwing; and replay reset. Assert no exception escapes and failed persistence still suppresses replay within the session. Run `npm test -- src/promotion/tourProgress.test.ts`; confirm failure before implementation.
- [ ] Implement bounded schema validation and deduplicated IDs without a dependency or backend API. Never store tokens, names, media, or session credentials. Use in-memory fallback on storage errors; do not clear unrelated browser storage.
- [ ] Rerun the same tests and require pass.

## Task 5: Contextual Turkish tours and Help

**Files:** Create tour UI/data/test files in the map; modify `App.tsx` for Help and tour integration, and add stable `data-tour` attributes to existing dashboard, package, review, and settings controls. Reuse `promotion.css`. Change package manifests only if a tour dependency is selected.

**Interfaces:** `TourId = 'dashboard' | 'package' | 'review' | 'settings'`; `TourStep = { id: string; target: string; title: string; description: string }`; `Walkthrough({ clientId, tour, enabled }: { clientId: number; tour: TourId; enabled: boolean }): JSX.Element | null`. Export `replayTours(clientId: number): void` to reset progress and restart the current eligible tour through an explicit event, without navigation or product mutations.

- [ ] Inspect the public Kompassify demo read-only. Research current documentation for a minimal maintained free/open-source tour library, starting with Driver.js; confirm license, controlled lifecycle hooks, focus behavior, and teardown. Use it only if it reduces code while meeting the spec; otherwise use a small local adapter. Record the choice and exact installed version in implementation notes, not a generic tour framework.
- [ ] Add unit/browser tests before implementation for first eligible display, setup precedence, each-step completion, reload suppression, close/Escape dismissal, skip-all including other pages, Help replay, and unavailable-storage fallback. Test target disappearance, route unmount, and a competing product dialog; assert overlay teardown and no accidental product API writes. Run these tests and confirm failure.
- [ ] Implement only four short page tours using real `data-tour` targets. Use Turkish labels `İleri`, `Geri`, `Tüm tanıtımları geç`, and close. Persist a step only after advancing past it; closing marks that tour dismissed; skip-all sets the global client preference. Exclude absent targets and state-ineligible controls. A missing target never marks an unseen step complete or traps navigation.
- [ ] Integrate Help actions for introduction and tour replay. Use the current client ID and existing navigation guards. Automatic tours require completed setup, live usable page data, and no competing product dialog. Tear down on page/client changes; dismiss safely on target loss. Tour controls never click product controls or perform uploads/saves/approval/navigation on behalf of users.
- [ ] Add focus-entry/restoration, visible keyboard focus, labeled popup, viewport-aware placement, and reduced-motion support. Test long Turkish text and narrow viewports with browser zoom-equivalent sizing; assert all controls visible and no horizontal overflow. Run `npm test -- src/promotion` and `npx playwright test e2e/walkthrough.spec.ts` from `web`; require pass. Update existing tests only to explicitly dismiss/suppress tours when testing unrelated workflows, not to weaken behavior assertions.

## Task 6: Consistent English documentation and bilingual announcement

**Files:** Replace `README.md`. Create `docs/guide/getting-started.md`, `publishing-a-reel.md`, `settings-and-recovery.md`, `docs/cv.md`, `docs/linkedin.md`, and `docs/guide/check-promotion.mjs`. Update Task 2 capture notes with final evidence.

**Interfaces:** README is the sole root introduction and links to the three English guides. Guides refer to visible Turkish controls by their exact labels. All channels reuse Task 2 assets, verified capabilities, and release links.

- [ ] Add a dependency-free Node check in `check-promotion.mjs` scoped to these deliverables: assert local Markdown/image links resolve; referenced screenshots exist; README final level-two section is Android; CV has the four required headings; LinkedIn has both language sections, images, hashtags, and attachment instructions. Assert README/guide command fences contain PowerShell, not inline Python/SQL snippets. Run `node docs/guide/check-promotion.mjs`; confirm missing deliverables cause a clear nonzero result.
- [ ] Write README introduction, practical benefits, requirements, Task 1 copy/paste startup, pairing and first browser use, short shared publishing flow, and detailed guide links. End with Android screenshots, verified APK/checksum links, installation/connection instructions, and release limitations. Do not represent a blocked APK/capture requirement as fulfilled.
- [ ] Write the three guides from current UI/code and verified behavior only, without consulting archived Turkish Markdown. Explain first setup, media preparation, retained sections, stale renders, approval eligibility, skip/reschedule, confirmed completion, settings, and recovery. Include more screenshots than README where helpful. Separate external Meta requirements from local startup.
- [ ] Write `cv.md` in simple English with short product summary, evidenced capability metrics, and `Architect & Leadership & Soft skills`, `Frontend skills`, `Backend skills`, `DevOps skills`. Connect capabilities to benefits without unsupported performance or personal/team claims. Keep source/evidence notes separate from paste-ready CV text.
- [ ] Write `linkedin.md` with matching Turkish/English semi-formal posts, shared workflow and approval boundary, relevant hashtags, and a few embedded screenshots. Provide paste-ready text separately from local image captions/attachment order so LinkedIn upload limitations are clear.
- [ ] Run the Node check, then manually follow the documented flow in an isolated browser setup. Verify commands match Task 1 and release links still resolve. Record unrun infrastructure/device checks explicitly in `screenshots.md`.

## Final verification and handoff

- [ ] From `web`, run `npm run typecheck`, `npm run build`, `npm test`, and `npm run test:browser`. Require exit 0; investigate regressions rather than hiding them.
- [ ] Run `powershell -NoProfile -File ops/tests/start-local.Tests.ps1` and `node docs/guide/check-promotion.mjs`; require exit 0. Repeat isolated quick-start smoke test if Docker is available.
- [ ] Inspect landing and walkthroughs in the browser at desktop/mobile widths and in reduced-motion mode; review every shipped screenshot and all factual claims.
- [ ] Run `git diff --check` and inspect `git status --short`. Confirm user guide moves and archive contents are untouched, generated secrets/data are untracked/ignored appropriately, and no commits were created.
- [ ] Report delivered paths, actual test results, and remaining release/device/infrastructure blockers. Do not claim full completion while requested screenshots or usable APK links remain unavailable.

## Plan self-review

The tasks cover the approved story, all four content channels, safe local startup, real web/Android assets, scroll-integrated movement, one-time tours, replay/skip behavior, accessibility, and verification. No task permits real Instagram publication or commits. The five review-focus conditions have explicit owning checks. Execution method and implementation approval remain pending.
