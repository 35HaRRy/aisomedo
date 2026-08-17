# Branding and Draft Configuration — Design

Date: 2026-08-17
Source: Issue #11 (part of #1, Dojo Reel Publishing MVP), blocked by #5 (done).

## Problem

Every Reel must carry a mandatory dojo logo watermark, optionally framed by
global intro/outro assets and durations, and start from reusable caption copy.
Defaults are installation-wide, but each package draft must be independently
editable without altering the globals.

## Decisions

1. **Seam placement**: extend the deep `DojoPublishing` facade (`dojo/publishing.py`),
   same as #7/#8/#9/#10. Caption and branding already live on the eight-key
   filesystem manifest (`manifest.caption`, `manifest.branding`); no new tables,
   no migration.
2. **Globals live in settings**: installation-wide defaults are `SettingsStore`
   keys (`branding.logo_asset`, `branding.intro_asset`, `branding.intro_duration`,
   `branding.outro_asset`, `branding.outro_duration`, `branding.caption_template`),
   mirroring the upload/montage limits pattern.
3. **Drafts copy globals at creation**: `_create_active_package` seeds the new
   manifest's `branding` and `caption` from the current globals, so every draft
   (including the one created immediately after completion) starts from defaults.
4. **Per-package edits never touch globals**: `set_caption`/`set_branding` write
   only the active manifest; globals are untouched. `set_branding` merges the
   caller's dict over the seeded draft so untouched fields survive.
5. **Replacement-field vocabulary is open**: caption text is stored and returned
   as opaque text. No `{{...}}` vocabulary is validated or locked; a later
   configuration decision owns the field names.
6. **Edits mark the render stale**: successful caption/branding edits clear
   `manifest.render_revision`, matching montage/new-media behavior.
7. **Logo watermark is mandatory**: `publish` refuses with `LogoNotConfigured`
   until `branding.logo_asset` is set. Actual watermark rendering is #12.
8. **Onboarding checklist extends**: `DojoSetup.checklist()` adds `logo` and
   `caption_template` items gating `is_ready`, wired through a `SettingsStore`.
9. **Auth**: all routes sit behind `get_current_client`; device + browser equal.

## Domain model

- `BrandingConfig` (frozen dataclass): `logo_asset`, `intro_asset`,
  `intro_duration`, `outro_asset`, `outro_duration`, `caption_template`, each
  optional; `to_dict()` emits all six keys.

## Exceptions

- `LogoNotConfigured(DojoError)`.

## Facade (`dojo/publishing.py`)

- `get_branding_defaults() -> BrandingConfig` — read settings.
- `set_branding_defaults(config, requester) -> BrandingConfig` — write globals,
  audit `branding.defaults_updated`.
- `get_draft_branding() -> dict` — active manifest `branding`.
- `get_draft_caption() -> str | None` — active manifest `caption`.
- `set_branding(branding, requester) -> dict` — merge into manifest `branding`,
  clear render revision, audit `branding.draft_updated`.
- `set_caption(caption, requester) -> str` — set manifest `caption`, clear render
  revision, audit `caption.draft_updated`.
- `_seed_draft_defaults(package)` — copy globals into a new manifest.
- `_assert_logo_configured()` — raise `LogoNotConfigured` when logo unset. The
  active draft's own `branding.logo_asset` wins over the global; a `None` draft
  value falls back to the global logo.
- `publish` calls `_assert_logo_configured()` before its deferred (#18) work.

`DojoSetup` (`dojo/setup.py`) gains `settings: SettingsStore | None = None`
(defaulting to the setup store) and checklist items `logo` (complete when
`branding.logo_asset` set) and `caption_template` (complete when
`branding.caption_template` set).

## FastAPI integration

- `backend/routes/packages.py`: `GET/PUT /api/packages/active/caption`,
  `GET/PUT /api/packages/active/branding` (404 no-active-package).
- `backend/routes/settings.py` (new) under `/api/settings`: `GET/PUT
  /api/settings/branding` for the installation-wide defaults.

## CLI

`backend/cli.py` `dojo-settings` gains `set-branding ...` and
`set-caption-template --text ...`, requester `"cli"`.

## Out of scope

- Actual watermark rendering, intro/outro composition, 1080x1920 fit — #12.
- Web/Android onboarding + branding UIs (tickets #26, #32).
- Final replacement-field vocabulary — a later configuration decision.