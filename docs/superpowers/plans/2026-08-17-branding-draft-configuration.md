# Branding and Draft Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship branding and draft configuration for issue #11: installation-wide branding defaults (logo, intro/outro, caption template), copied into each package draft at creation and overridable per package without touching globals, with the replacement-field vocabulary left open and the logo watermark required before publish.

**Architecture:** Extend the deep `DojoPublishing` facade (`dojo/publishing.py`) and `DojoSetup` (`dojo/setup.py`). Globals live in `SettingsStore`; drafts live on the existing manifest `caption` + `branding`. No new tables, no migration. New routes on the `packages` router plus a new `settings` router.

**Tech Stack:** Python 3.12 (uv workspace), FastAPI, pytest, ruff, mypy. Domain tests via the in-memory seam; contract tests via FastAPI `TestClient`.

## Global Constraints

- Python `requires-python = ">=3.12"`.
- Domain vocabulary from `CONTEXT.md` / `docs/specs/dojo-reel-publishing-mvp.md`: active `Dojo Paylaşım Paketi`, manifest contract. No new domain nouns.
- One primary seam: `DojoPublishing`. Tests assert externally visible domain outcomes.
- Draft = manifest `caption` + `branding`, seeded from globals at package creation.
- Settings keys: `branding.logo_asset`, `branding.intro_asset`, `branding.intro_duration`, `branding.outro_asset`, `branding.outro_duration`, `branding.caption_template`. No migration.
- Per-package edits write manifest only; globals untouched. `set_branding` merges over the seeded draft.
- Replacement-field vocabulary stays open: caption is opaque text, never validated.
- Edits clear `render_revision`.
- `publish` raises `LogoNotConfigured` when logo unset (rendering is #12).
- `DojoSetup.checklist()` adds `logo` + `caption_template` items gating `is_ready`.
- Routes behind `get_current_client`; equal privilege device + browser; unauth → 401.
- Lint: ruff (`E,F,I,UP`). dojo-core mypy `disallow_untyped_defs`; backend mypy `strict`.
- Commands run from repo root. Tests use `FakeClock` for deterministic time.

---

### Task 1: Models, exceptions, exports

**Files:** `dojo-core/src/dojo/model.py`, `dojo-core/src/dojo/exceptions.py`, `dojo-core/src/dojo/__init__.py`

- [ ] **Step 1: Add `BrandingConfig`** to `model.py` (before `MontageLimits`) with `logo_asset`, `intro_asset`, `intro_duration`, `outro_asset`, `outro_duration`, `caption_template` (all `str | None`/`float | None` default `None`) and `to_dict()`.
- [ ] **Step 2: Add `LogoNotConfigured(DojoError)`** to `exceptions.py`.
- [ ] **Step 3: Export both** from `__init__.py` imports + `__all__`.

```bash
git add dojo-core/src/dojo/model.py dojo-core/src/dojo/exceptions.py dojo-core/src/dojo/__init__.py
git commit -m "feat(dojo-core): branding config model and exception (#11)"
```

---

### Task 2: Facade — defaults, seeding, caption, branding, logo guard

**Files:** `dojo-core/src/dojo/publishing.py`

- [ ] **Step 1: Imports** — add `LogoNotConfigured` to exceptions import; `BrandingConfig` to model import.
- [ ] **Step 2: Seed drafts** — in `_create_active_package`, after `packages.create`, call `self._seed_draft_defaults(package)`.
- [ ] **Step 3: Methods** (place near `_write_manifest`): `get_branding_defaults()`, `set_branding_defaults(config, requester)`, `_seed_draft_defaults(package)`, `get_draft_branding()`, `get_draft_caption()`, `set_branding(branding, requester)`, `set_caption(caption, requester)`, `_assert_logo_configured()`.
- [ ] **Step 4: Replace stubs** — remove the old `set_caption` stub; `publish` calls `self._assert_logo_configured()` before `raise NotImplementedError`.

```bash
git add dojo-core/src/dojo/publishing.py
git commit -m "feat(dojo-core): branding and caption draft config on publishing seam (#11)"
```

---

### Task 3: Setup checklist items

**Files:** `dojo-core/src/dojo/setup.py`

- [ ] **Step 1:** import `cast`, `SettingsStore`; add `settings: SettingsStore | None = None` param (default `cast(SettingsStore, setup)`); add `LOGO_ITEM`, `CAPTION_TEMPLATE_ITEM` constants.
- [ ] **Step 2:** `checklist()` appends `logo` (complete when `branding.logo_asset` set) and `caption_template` (complete when `branding.caption_template` set).

```bash
git add dojo-core/src/dojo/setup.py
git commit -m "feat(dojo-core): logo and caption-template onboarding checklist items (#11)"
```

---

### Task 4: Domain tests

**Files:** `dojo-core/tests/test_branding.py` (new), `dojo-core/tests/test_setup.py`

- [ ] **Step 1:** create `test_branding.py` covering: empty defaults; set defaults persists + audits; create package seeds defaults; empty seed when no defaults; completion creates next seeded package; per-package caption/branding override leaves globals; opaque field passthrough; edits clear `render_revision`; `publish` raises `LogoNotConfigured` without logo and passes guard with logo; no-active-package guards.
- [ ] **Step 2:** update `test_setup.py` — add `configure_branding` helper; `test_is_ready_requires_all_items` needs branding configured to be ready; add `test_checklist_branding_tracks_logo_and_caption_template`.

```bash
git add dojo-core/tests/test_branding.py dojo-core/tests/test_setup.py
git commit -m "test(dojo-core): branding and draft configuration domain tests (#11)"
```

---

### Task 5: Backend routes

**Files:** `backend/src/backend/routes/packages.py`, `backend/src/backend/routes/settings.py` (new), `backend/src/backend/main.py`

- [ ] **Step 1:** `packages.py` — add `CaptionIn`, `BrandingIn` Pydantic bodies; add `GET/PUT /api/packages/active/caption` and `GET/PUT /api/packages/active/branding` (404 on `NoActivePackage`).
- [ ] **Step 2:** new `settings.py` — `GET/PUT /api/settings/branding` for globals via `BrandingDefaultsIn/Out`.
- [ ] **Step 3:** register `settings_router` in `main.py` behind `get_current_client`.

```bash
git add backend/src/backend/routes/packages.py backend/src/backend/routes/settings.py backend/src/backend/main.py
git commit -m "feat(backend): branding, caption, and settings routes (#11)"
```

---

### Task 6: Backend CLI

**Files:** `backend/src/backend/cli.py`

- [ ] **Step 1:** add `set_branding_defaults(publishing, *, config)` helper (requester `"cli"`).
- [ ] **Step 2:** `settings_main` — add `set-branding ...` and `set-caption-template --text ...` subcommands building `DojoPublishing`.

```bash
git add backend/src/backend/cli.py
git commit -m "feat(backend): branding and caption-template settings CLI (#11)"
```

---

### Task 7: Contract tests

**Files:** `backend/tests/test_api.py`, `backend/tests/test_cli.py`

- [ ] **Step 1:** `test_api.py` — branding/caption/settings routes auth → 401; set+get global defaults; set+get caption via API leaves global template; set+get branding via API.
- [ ] **Step 2:** `test_cli.py` — `set_branding_defaults` and `set_caption_template` audit `"cli"`.

```bash
git add backend/tests/test_api.py backend/tests/test_cli.py
git commit -m "test(backend): branding and caption contract tests (#11)"
```

---

### Task 8: Docs

**Files:** `docs/superpowers/specs/2026-08-17-branding-draft-configuration-design.md` (new), this plan doc.

- [ ] **Step 1:** write the design doc and this plan doc.

```bash
git add docs/superpowers/specs/2026-08-17-branding-draft-configuration-design.md docs/superpowers/plans/2026-08-17-branding-draft-configuration.md
git commit -m "docs: branding and draft configuration design and plan (#11)"
```

---

### Task 9: Verification

- [ ] **Step 1:** `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests; uv run --project dojo-core mypy dojo-core/src/dojo; uv run --project dojo-core pytest dojo-core/tests -v`
- [ ] **Step 2:** `uv run --project backend ruff check backend/src backend/tests; uv run --project backend mypy backend/src/backend; uv run --project backend pytest backend/tests -v`
- [ ] **Step 3:** `/code-review`, then commit any fixes.