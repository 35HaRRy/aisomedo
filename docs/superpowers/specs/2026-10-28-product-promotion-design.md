# Aisomedo Product Promotion Design

## Status and workflow

- [x] Inspect the existing application, documentation, and release workflow.
- [x] Confirm the shared story and integrated promotion approach with the owner.
- [x] Establish that no measured business metrics are available.
- [x] Write and self-review this design.
- [x] Owner reviews this written design, including scroll-integrated landing behavior.
- [x] Write and review the implementation plan; choose its execution method (inline, current checkout).
- [ ] Implement and verify the approved plan.

Do not commit any changes. Preserve existing user changes, including the guide relocation. Do not read or reuse Markdown files under `docs/guide/archive-tr/`, or recover their old copies for use as source material.

## Purpose

Introduce Aisomedo to potential users and employers through one consistent story, then help new users complete that story in the web application. The deliverables are a replacement README, English guides, a CV project section, a bilingual LinkedIn post, a Turkish landing page, and Turkish contextual walkthroughs.

Aisomedo helps administrators turn collected photos and videos into branded Instagram Reels. Users prepare a Paylaşım Paketi, review the rendered result, and approve publication. Scheduling does not bypass human approval. A package becomes a Tamamlanmış Paket only after Instagram confirms publication.

## Shared story and claims

Use this sequence everywhere:

1. Collect photos and videos in the active package.
2. Order media, select retained video sections, and prepare branding and captions.
3. Render and review the Reel.
4. Approve publication when eligible, or skip or reschedule the review.
5. Find confirmed publications in completed packages and inspect activity history.

English copy uses short sentences and common words. Turkish copy uses plain language and the domain terms from `CONTEXT.md`. Do not imply that Aisomedo generates source media with AI, supports other social networks, publishes without approval, or has account roles that do not exist.

No measured business results are available. Do not claim percentage improvements, time savings, user counts, publication success rates, or leadership outcomes without evidence. CV metrics may describe verified product capabilities, such as rendered output dimensions and supported clients. Distinguish technical specifications from measured benefits. Any timing result must identify its method and conditions; otherwise omit it.

Describe architecture and project ownership without inventing team size, management responsibilities, or employment history. The owner must be able to reuse the CV text without inheriting unverified personal claims.

## Existing integration points

- `web/src/App.tsx` gates paired and unpaired sessions. Paired clients enter the existing workspace.
- `web/src/navigation.ts` owns hash navigation and unsaved-edit guards. Promotion must not bypass those guards.
- `web/src/onboarding/` already implements required setup. Promotional walkthroughs are separate from required configuration and consent.
- The web application uses React, TypeScript, and existing CSS, with Vitest and Playwright checks available.
- `ops/docker-compose.yml` provides backend, database, initialization, and worker services. Its current setup is not itself a complete one-command web quick start; instructions must be verified rather than copied unchanged.
- `.github/workflows/android-release.yml` publishes signed `aisomedo.apk` and `aisomedo.apk.sha256` assets for `android-v*` tags. This is evidence of release machinery, not evidence that a downloadable release currently exists.

## Deliverable 1: README and English guides

Replace the root `README.md`; do not create a competing `READ.ME` entry point.

README sections, in order:

1. A short introduction and one strong web screenshot.
2. The practical benefits and the human-approval boundary.
3. Requirements and a copy-and-paste PowerShell quick start.
4. First browser use: pairing, required setup, and entry to the working dashboard.
5. The shared publishing story, illustrated only at important steps, with links to detailed guides.
6. A compact architecture/development reference as needed, keeping operational detail in guides.
7. Android screenshots, APK/checksum download links, installation and pairing steps.

All usage instructions and workflow screenshots use the web application. Android instructions cover installation and connection, not a second mobile workflow tutorial. Mobile screenshots appear in the final Android section.

Quick-start requirements:

- Use PowerShell commands, with no inline Python or SQL code.
- Prefer existing operator CLIs and Docker Compose. Add a small PowerShell entry point only if existing commands cannot provide a reliable, concise path.
- Document prerequisites and expected URLs before commands need them.
- Fail clearly on missing prerequisites. Do not overwrite an existing environment file or existing secrets, reset data, or expose credentials in documentation.
- Supply a runnable block for each genuinely separate stage rather than mixing long-running foreground servers into an unusable block.
- Explain the credentials and external Instagram prerequisites that cannot be automated; do not claim local startup alone enables real publishing.

Create English guides under `docs/guide/`:

- `getting-started.md`: requirements, PowerShell startup, browser pairing, first setup, Android installation/connection, and common startup issues.
- `publishing-a-reel.md`: upload, ordering, retained video sections, caption/branding, rendering, review, approval eligibility, skip/reschedule, and confirmed completion.
- `settings-and-recovery.md`: settings, connection health, upload conflicts/recovery, stale renders, failed publication, and activity inspection, limited to verified UI behavior.

The guides may use more screenshots than the README. Keep visible Turkish UI labels in English instructions so users can find the actual controls.

## Deliverable 2: CV project section

Write `docs/cv.md` in simple English:

- Project name and a short product explanation consistent with the README.
- Benefits supported by verified technical numbers, with no fabricated before/after comparison.
- Sections named `Architect & Leadership & Soft skills`, `Frontend skills`, `Backend skills`, and `DevOps skills`.
- Evidence-based engineering experience: system boundaries, user safety, web UX, native Android, API/domain logic, background processing, persistence, deployment, and release checks where implementation supports them.
- No screenshots. Keep the result suitable for extracting into a CV, not a full architecture article.

## Deliverable 3: LinkedIn post

Write `docs/linkedin.md` with Turkish and English versions of the same semi-formal announcement. Introduce the problem, explain the shared workflow, highlight human approval, and close with an invitation for feedback.

Embed a few selected application screenshots in the Markdown, with short captions and an explicit attachment order. LinkedIn does not render local Markdown images inside post text; provide clean paste-ready text and identify the files to attach. Include a small relevant hashtag set. Do not invent a public demo URL or metrics.

## Shared visual assets

Store reusable captures and original promotional artwork in `web/public/promotion/`, with web and Android captures in separate subdirectories. Documentation uses relative links to those files; the landing page uses their public URLs.

Use one coherent example package across captures. Capture rendered application screens, not fabricated interface mockups. Use controlled sample media and no identifiable students, private names, tokens, pairing codes, host details, or other sensitive data.

Prefer an isolated local application with synthetic data. Existing deterministic browser fixtures may prepare UI states, but fixture-backed screenshots must be identified in the asset notes and must not be represented as evidence of a real Instagram publication. Record capture source, scenario, and any Android device/emulator requirements in `docs/guide/screenshots.md`.

Capture the dashboard, media editor, retained-section editor, rendered review, and completed-package view when those states are available. README and LinkedIn reuse a smaller subset. Capture Android screens from the actual Android app, not the web app at a narrow viewport. If capture tooling or releases are unavailable, report the blocker; do not substitute invented assets or broken links and call the requirement complete.

## Deliverable 4: Turkish landing page

Serve a public introduction at `#/welcome`, and show it for unpaired visitors arriving without a specific application destination. Provide an explicit `Uygulamayı aç` action leading to pairing at `#/pair`; already paired users retain their normal workspace entry and deep links. Paired users can reopen the introduction from Help without losing unsaved work.

Page sections:

- A focused hero explaining the product and linking to the application and workflow.
- Benefit cards with icons, original SVG artwork, and genuine screenshots.
- The shared upload-to-publication story with a clear human-approval checkpoint.
- A compact Android preview and verified download links when available.
- A final application-entry action.

Reuse the existing visual identity and theme behavior. Use original SVG/CSS artwork rather than a new illustration service. The page is a multi-section scrolling story, not content compressed into one viewport. Section links and actions such as `Akışı keşfet` and `Sonraki adım` move smoothly to the relevant section; all sections also remain reachable through ordinary scrolling and keyboard navigation.

Motion must be integrated with scrolling, not limited to one-time card reveals. In the workflow section, keep a visual stage sticky on suitable desktop viewports while successive text steps scroll alongside it. The active step changes its screenshot, highlights, and restrained icon/artwork transitions as the reader moves through the story. Section navigation indicates the currently visible section. On narrow screens, use normal document flow with each visual beside its corresponding text rather than a pinned layout that crowds the content.

Use browser-native observation and CSS for section activation and transitions; use continuous scroll-linked animation only where it improves the explanation, with a readable static fallback. Respect `prefers-reduced-motion` for both animation and button-triggered smooth scrolling. Avoid scroll hijacking, forced snapping, autoplay navigation, and unnecessary animation dependencies. Images have explicit dimensions, meaningful alternative text, and sensible loading behavior.

## Deliverable 5: Contextual walkthroughs

Provide a Kompassify-like interaction pattern: highlight a real control and explain it in a short Turkish popup. Do not embed or depend on the hosted Kompassify service. Inspect its public demo for interaction reference before implementation.

Use page-specific tours for the dashboard, active package/media editing, review, and settings. Show only steps whose target exists and whose operation is meaningful in the current state. Required setup takes precedence; no promotional overlay competes with consent or the setup wizard.

Controls: `İleri`, `Geri`, `Tüm tanıtımları geç`, and a clear close action. Escape closes the current tour and marks it dismissed so it does not reopen automatically. Closing or skipping never performs a product action. Users must explicitly perform uploads, save edits, approve publication, or change settings themselves.

Persist completed and dismissed step IDs in a versioned browser-local record scoped to the paired client. Completing or dismissing a tour suppresses its automatic replay in that browser. `Tüm tanıtımları geç` suppresses every automatic tour, including tours on pages not yet visited. Help provides explicit replay. Cross-device synchronization is outside scope, and clearing browser storage resets this preference.

If browser storage is blocked, use in-memory suppression for the current session; do not break application use. If a target disappears, navigate away, or a higher-priority product dialog opens, dismiss the overlay safely without claiming unseen steps were completed. Missing targets must not trap navigation or leave a permanent backdrop.

Meet keyboard and screen-reader basics: labeled popup, visible focus, sensible focus entry and restoration, viewport-aware placement, and no clipping on mobile. Do not auto-navigate between pages or bypass unsaved-edit guards. Prefer a maintained free/open-source tour library if it covers accessible positioning and focus behavior with less code than a custom implementation; verify its license and current API before selecting it. Do not build a general onboarding platform or add a backend persistence API.

## Verification and acceptance

- Run web type checking, production build, and relevant unit/browser tests.
- Test public entry, pairing entry, paired deep links, and return from Help without discarding edits.
- Test landing section buttons, active-section indication, scroll-driven workflow visuals, narrow-screen document flow, and reduced-motion fallbacks. Ordinary scrolling and keyboard navigation must reach all content without animation support.
- Test first display, per-step persistence, completed/dismissed suppression, skip-all across pages, explicit replay, unavailable storage, missing targets, route changes, keyboard controls, mobile placement, and reduced motion.
- Verify PowerShell syntax and exercise the documented startup path against an isolated installation when tooling permits. Record unexecuted infrastructure or device checks explicitly.
- Check documentation image links and guide links; verify APK/checksum links against actual release assets.
- Review all screenshots for privacy and consistent example data.
- Confirm the README ends with Android content, detailed workflow guides are English, promotional UI is Turkish, and LinkedIn includes both languages.
- Never publish to Instagram, deploy infrastructure, create a release, modify production data, or commit as part of this work.

## Scope boundaries

No new authentication model, analytics service, remote tour editor, cross-device tour synchronization, publishing behavior changes, or unrelated refactoring. Share screenshots and story, not a new cross-channel content-management framework.
