# Issue #32 discovery checklist

Path: architectural. The Android app has a compatibility screen but no existing
navigation, pairing, dashboard, or onboarding flow.

- [x] Explore issue, parent requirements, blockers, project context, and recent commits.
- [x] Assess visual companion need; no visual comparison required for approved native direction.
- [x] Confirm intended outcome and unresolved scope with the user.
- [x] Compare approaches and obtain approval of design sections.
- [x] Write the approved design specification.
- [x] Review specification for gaps, ambiguity, contradictions, and scope.
- [ ] Obtain user review of the written specification.
- [ ] Invoke writing-plans; obtain plan review and execution selection.

## Requirements and findings

- #3 and #24 are closed; #32 is ready-for-agent.
- Android 10+, Kotlin/Jetpack Compose, four navigation areas, Turkish resource strings.
- Dashboard: active package, next slot, pending actions, Instagram and worker health.
- Guided setup includes pairing, Instagram, schedule, consent, logo, caption, and optional cards.
- Consent acceptance is installation-wide and version-specific; newly paired clients inherit it.
- Backend already exposes pairing, dashboard, setup, consent, branding, plan, and Meta APIs.
- Generated Kotlin contract currently contains only compatibility types. Extend the existing generator for consumed schemas rather than hand-writing duplicate DTOs.
- Retain compatibility/update gating, version headers, revocation handling, and safe credential storage.
- Package editing, notifications, offline caching, and full activity/settings are separate tickets (#33–#38).

## Approved direction

Native Compose shell with lifecycle-owned state, generated API models, one HTTP
transport, and backend-derived setup progress. Bottom navigation on phones;
navigation rail and wider content on tablets. No new backend business rules,
dependency-injection framework, custom navigation framework, or offline database.

User approved this direction on 2026-10-04. Written specification:
docs/superpowers/specs/2026-10-04-android-shell-pairing-onboarding-design.md.
Written-spec approval is still required before implementation planning.
