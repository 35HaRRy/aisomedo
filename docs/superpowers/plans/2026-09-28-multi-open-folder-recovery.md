# Multi-open-folder recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Startup repair for multiple unsuffixed package folders per issue #20.

**Architecture:** New `DojoPublishing` repair/import methods own filesystem+DB reconciliation; FastAPI lifespan and worker startup call repair best-effort; recovered media re-enters via existing `start_upload` conflict path; `-resolved` rename plus manifest flag blocks re-import.

**Tech Stack:** Python, DojoPublishing seam, FastAPI, InMemory/Postgres stores.

**Spec:** `docs/specs/dojo-reel-publishing-mvp.md` stories 90-93 + decisions lines 144-148; issue #20.

## Global Constraints

- Portable folder names `dd-MM-yyyy HH-mm` in `Europe/Istanbul`; unsuffixed=active, `-publishing` claimed/uncertain, `-completed` confirmed, `-recovered` excluded recovery, `-resolved` handled.
- Zero-or-one active package invariant; never publish a recovered folder directly.
- Audit repair; notify administrators; contents preserved on rename.
- Tests assert observable domain outcomes through `DojoPublishing`, not private methods/SQL.

## Review Focus

- Unparseable dirname among unsuffixed candidates: treated oldest, never wins over valid timestamp.
- Repair with `-publishing` present: publishing folders untouched, not counted as open.
- Import with zero media files: resolves immediately without uploads, still audited.
- Double import after `-resolved`: rejected, no new uploads created.
- Notification adapter failure: repair still succeeds, no exception escapes.

---

### Task 1: Core repair in DojoPublishing

**Files:**
- Modify: `dojo-core/src/dojo/publishing.py`
- Test: `dojo-core/tests/test_recovery_folders.py`

**Interfaces:**
- Consumes: `PackageStore.get_active/create/update`, `AuditStore.append`, `Notifier.send`, `PACKAGE_FOLDER_FORMAT`, `ISTANBUL`.
- Produces: `repair_open_folders(*, requester: str | None = None) -> dict`, `_list_open_folders() -> list[Path]`, `_parse_folder_time(name: str) -> datetime | None`, `_ensure_db_active(folder_name, parsed) -> Package | None`, `_notify_recovery(active, recovered) -> None`.

- [ ] **Step 1: Write failing test** `test_newest_unsuffixed_wins_older_renamed_recovered` in `dojo-core/tests/test_recovery_folders.py`: two unsuffixed folders with manifests, call `repair_open_folders()`, assert newest stays, older becomes `<name>-recovered` with contents preserved, audit contains `package.recovery`.
- [ ] **Step 2: Run test, verify FAIL** Run: `uv run --project dojo-core pytest dojo-core/tests/test_recovery_folders.py -v` Expected: FAIL (method missing).
- [ ] **Step 3: Implement** `repair_open_folders`, `_list_open_folders` (skip `tmp` + suffixed `-publishing/-completed/-recovered/-resolved`), `_parse_folder_time` (strptime + ISTANBUL, None on failure), newest-first sort (parsed time, fallback mtime), atomic `Path.rename`, DB align via `_ensure_db_active`, `package.recovery` audit, best-effort `_notify_recovery`.
- [ ] **Step 4: Run test, verify PASS** Run same pytest. Expected: PASS.
- [ ] **Step 5: Commit** `git add dojo-core/... && git commit -m "feat(dojo-core): multi-open-folder startup repair (#20)"`.

### Task 2: Recovered import through conflict workflow + resolved marker

**Files:**
- Modify: `dojo-core/src/dojo/publishing.py`
- Test: `dojo-core/tests/test_recovery_folders.py`

**Interfaces:**
- Consumes: Task 1 repair, `start_upload/append_upload_range/complete_upload`, `_manifest_collisions`.
- Produces: `list_recovered_folders() -> list[str]`, `import_recovered_media(folder_name, *, requester) -> dict`, `mark_recovered_resolved(folder_name, *, requester) -> str`.

- [ ] **Step 1: Write failing tests** `test_import_goes_through_conflict`, `test_resolved_prevents_reimport`: import creates conflict upload for colliding name, receiving for fresh name; second import after `mark_recovered_resolved` raises `MediaNotFound`/`UploadConflict` and creates no uploads.
- [ ] **Step 2: Run, verify FAIL** Same pytest file. Expected: FAIL.
- [ ] **Step 3: Implement** `list_recovered_folders` (dirs ending `-recovered`), `import_recovered_media` (reject `-resolved`/flagged; read recovered manifest media entries; locate bytes under `media/<id>/`; `start_upload` per file so collisions become `conflict` status; append+complete only non-conflict; audit `package.recovered_import`), `mark_recovered_resolved` (set manifest `recovery.resolved=true`, rename `-recovered`→`-resolved`, audit `package.recovered_resolved`).
- [ ] **Step 4: Run, verify PASS** `uv run --project dojo-core pytest dojo-core/tests/test_recovery_folders.py -v`.
- [ ] **Step 5: Commit** `git commit -m "feat(dojo-core): recovered media import via conflict workflow (#20)"`.

### Task 3: Startup wiring + HTTP surface

**Files:**
- Modify: `backend/src/backend/main.py`, `backend/src/backend/routes/packages.py`, `worker/src/worker/main.py`
- Test: `backend/tests/test_packages_recovery.py`

**Interfaces:**
- Consumes: Task 1-2 methods.
- Produces: `GET /api/packages/recovered`, `POST /api/packages/recovered/{folder}/import`, `POST /api/packages/recovered/{folder}/resolve`; lifespan/worker best-effort `repair_open_folders`.

- [ ] **Step 1: Write failing route tests** repair-on-lifespan covered by seam tests; routes: list returns recovered names; import returns upload ids; resolve renames; double-resolve 404/409.
- [ ] **Step 2: Run, verify FAIL** `uv run --project backend pytest backend/tests/test_packages_recovery.py -v`.
- [ ] **Step 3: Implement** lifespan repair try/except; worker `build_publishing` + `main` startup repair try/except; three routes mapping `MediaNotFound→404`, conflict/double→409.
- [ ] **Step 4: Run, verify PASS** Same backend pytest + `uv run --project dojo-core pytest dojo-core/tests/test_recovery_folders.py -v`.
- [ ] **Step 5: Commit** `git commit -m "feat(backend,worker): wire multi-open-folder recovery startup and routes (#20)"`.
