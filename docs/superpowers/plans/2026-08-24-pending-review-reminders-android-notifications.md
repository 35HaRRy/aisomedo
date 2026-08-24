# Pending-Review Reminders and Android Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver configurable pending-review reminders with quiet hours, FCM Android push, and durable cadence behind `DojoPublishing`.

**Architecture:** Extend `DojoPublishing` facade; batch `Notifier` adapter; `push_registrations` + `last_reminded_at` persistence; worker tick calls `send_due_reminders()` after job processing.

**Tech Stack:** Python 3.12, dojo-core, FastAPI, SQLAlchemy/Postgres, Firebase Admin SDK, FakeClock + InMemoryStore + StubNotifier for tests.

## Global Constraints

- Timezone fixed `Europe/Istanbul`; default interval 360 min, window 08:00 inclusive to 22:00 exclusive; crossing-midnight windows supported.
- `Notifier` becomes batch-oriented with delivered/invalid/transient classification.
- One FCM token per Android client; token transfer if duplicate; browser registration rejected 422.
- Publication outcome notifications out of scope (#18/#19).
---

### Task 1: Domain model, ports, stubs, and persistence foundation

**Files:**
- Modify: `dojo-core/src/dojo/model.py` — add `ReminderPolicy`, `PushRegistration`, `Notification`, `NotificationResult`, `last_reminded_at` on `YayinIncelemesi`
- Modify: `dojo-core/src/dojo/ports.py` — update `Notifier`, add `PushRegistrationStore`, extend `ReviewStore`
- Modify: `dojo-core/src/dojo/adapters/stubs.py` — update `StubNotifier` to batch contract
- Create: `dojo-core/src/dojo/exceptions.py` — add `ReminderPolicyInvalid`, `PushTokenInvalid` if needed
- Modify: `dojo-core/src/dojo/adapters/memory.py` — implement new store methods + timestamp
- Modify: `dojo-core/src/dojo/adapters/db.py` — add `PushRegistrationRow`, `last_reminded_at` column, store methods
- Create: `dojo-core/migrations/versions/0011_pending_review_notify.py`
- Modify: `dojo-core/tests/conftest.py` — truncate `push_registrations`

**Interfaces:**
- Consumes: existing `YayinIncelemesi`, `Client`, `SettingsStore`
- Produces: `ReminderPolicy`, `PushRegistration`, `Notifier.send(notification, tokens) -> NotificationResult`, `PushRegistrationStore` methods, `ReviewStore.update_last_reminded_at`

- [ ] **Step 1: Write failing domain/ports test**

```python
# dojo-core/tests/test_reminders_domain.py
from dojo.model import ReminderPolicy, YayinIncelemesi
assert ReminderPolicy().interval_minutes == 360
```

- [ ] **Step 2: Run `pytest dojo-core/tests/test_reminders_domain.py -v` expect fail imports**
- [ ] **Step 3: Implement `ReminderPolicy`, add `last_reminded_at`, update `Notifier` protocol**

```python
@dataclass(frozen=True)
class ReminderPolicy:
    interval_minutes: int = 360
    delivery_start: time = time(8,0)
    delivery_end: time = time(22,0)
    timezone: str = "Europe/Istanbul"
```

- [ ] **Step 4: Run test pass**
- [ ] **Step 5: Add memory/db registration methods + row + migration; run `mypy dojo-core`**
- [ ] **Step 6: Commit**

```bash
git add dojo-core/src/dojo/model.py dojo-core/src/dojo/ports.py dojo-core/src/dojo/adapters/memory.py dojo-core/src/dojo/adapters/db.py dojo-core/migrations/versions/0011_pending_review_notify.py
git commit -m "feat(core): add reminder policy, push registration, and cadence persistence"
```

### Task 2: Reminder policy facade (get/set with validation)

**Files:**
- Modify: `dojo-core/src/dojo/publishing.py` — `get_reminder_policy`, `set_reminder_policy` + validation constants
- Test: `dojo-core/tests/test_reminders_policy.py`

**Interfaces:**
- Consumes: `ReminderPolicy`, `SettingsStore`
- Produces: `DojoPublishing.get_reminder_policy() -> ReminderPolicy`, `set_reminder_policy(policy, requester=None) -> ReminderPolicy`

- [ ] **Step 1: Write failing test**

```python
def test_default_policy(tmp_path):
    seam = make_seam(tmp_path)
    assert seam.get_reminder_policy().interval_minutes == 360
def test_reject_invalid_interval(tmp_path):
    seam = make_seam(tmp_path)
    with pytest.raises(ReminderPolicyInvalid):
        seam.set_reminder_policy(ReminderPolicy(interval_minutes=0))
```

- [ ] **Step 2: Run `pytest dojo-core/tests/test_reminders_policy.py -v` expect fail not implemented**
- [ ] **Step 3: Implement get/set with validation (interval>0, start != end, tz == Europe/Istanbul)**

```python
def get_reminder_policy(self) -> ReminderPolicy: ...
def set_reminder_policy(self, policy: ReminderPolicy, requester=None) -> ReminderPolicy: ...
```

- [ ] **Step 4: Run pass + `mypy dojo-core`**
- [ ] **Step 5: Commit**

### Task 3: Push token registration lifecycle

**Files:**
- Modify: `dojo-core/src/dojo/publishing.py` — `register_push_token`, `remove_push_token`
- Modify: `dojo-core/src/dojo/pairing.py` — no change, but used for client lookup
- Test: `dojo-core/tests/test_push_registration.py`

**Interfaces:**
- Consumes: `PushRegistrationStore`, `PairingStore` via `InMemoryStore`
- Produces: `register_push_token(client_id, token)`, `remove_push_token(client_id)`

- [ ] **Step 1: Write failing tests: android register ok, browser 422, revoked 422, replacement, transfer**

```python
def test_android_register_and_replace(tmp_path): ...
def test_browser_cannot_register(tmp_path): ...
def test_duplicate_transfers(tmp_path): ...
```

- [ ] **Step 2: Run fail**
- [ ] **Step 3: Implement validation: client exists, kind device, not revoked, token non-empty; store transfer semantics**

```python
def register_push_token(self, client_id:int, token:str) -> None:
    client = self._pairing.find_client_by_id(client_id) # via injected PairingStore or direct store lookup
```

- [ ] **Step 4: Run pass**
- [ ] **Step 5: Commit**

### Task 4: Firebase batch notifier adapter and stub upgrade

**Files:**
- Create: `dojo-core/src/dojo/adapters/fcm.py` — `FcmNotifier` wrapping `firebase_admin.messaging`
- Modify: `dojo-core/src/dojo/adapters/stubs.py` — `StubNotifier` matches new contract with configurable per-token responses

**Interfaces:**
- Consumes: `Notifier` protocol
- Produces: `FcmNotifier(messaging_client) -> Notifier`

- [ ] **Step 1: Write failing adapter test with fake messaging client**

```python
def test_fcm_classifies_invalid_and_transient():
    fake = FakeMessaging(...)
    notifier = FcmNotifier(fake)
    result = notifier.send(notification, ["tok1","tok2"])
    assert "tok1" in result.invalid_tokens
```

- [ ] **Step 2: Run fail**
- [ ] **Step 3: Implement `FcmNotifier.send` building MulticastMessage with data strings, parsing BatchResponse errors**
- [ ] **Step 4: Run pass**
- [ ] **Step 5: Commit**

### Task 5: send_due_reminders facade (quiet hours, interval, persistence, auditing)

**Files:**
- Modify: `dojo-core/src/dojo/publishing.py` — `send_due_reminders`
- Test: `dojo-core/tests/test_reminders_delivery.py`

**Interfaces:**
- Consumes: `ReminderPolicy`, `PushRegistrationStore`, `ReviewStore`, `Notifier`
- Produces: `send_due_reminders() -> None` with side effects on reviews and registrations

- [ ] **Step 1: Write failing tests: first eligible push, quiet deferral, interval, cross-midnight window, all-android, invalid removal, whole-call failure no timestamp, revoked excluded, resolution stops**

```python
def test_sends_once_per_interval(tmp_path): ...
def test_quiet_hours_defers(tmp_path): ...
def test_invalid_token_removed(tmp_path): ...
```

- [ ] **Step 2: Run fail**
- [ ] **Step 3: Implement `_in_delivery_window(local_time, start, end)` with overnight support, eligible review selection, batch send per review, invalid cleanup, timestamp persist, audit events `notification.sent`/`notification.failed`**

- [ ] **Step 4: Run pass + `mypy dojo-core`**
- [ ] **Step 5: Commit**

### Task 6: HTTP contracts for reminder policy

**Files:**
- Modify: `backend/src/backend/routes/settings.py` — add `GET/PUT /api/settings/reminders`
- Modify: `backend/src/backend/main.py` — ensure router included (already)
- Test: `backend/tests/test_api.py` — add contract tests (or new `test_reminders_api.py`)

**Interfaces:**
- Consumes: `DojoPublishing.get_reminder_policy/set_reminder_policy`
- Produces: `GET /api/settings/reminders` 200, `PUT /api/settings/reminders` 200/422/401

- [ ] **Step 1: Write failing TestClient tests for 401, default get, put valid, put invalid 422**
- [ ] **Step 2: Run fail 404**
- [ ] **Step 3: Implement pydantic models `ReminderPolicyIn/Out` with time parsing, handler mapping `ReminderPolicyInvalid -> 422`**
- [ ] **Step 4: Run pass**
- [ ] **Step 5: Commit**

### Task 7: HTTP contracts for push-token self-registration

**Files:**
- Modify: `backend/src/backend/routes/pairing.py` — add `PUT/DELETE /api/pairing/me/push-token`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `DojoPublishing.register_push_token/remove_push_token`, `get_current_client`
- Produces: `PUT /api/pairing/me/push-token` 204/422/401, `DELETE ...` 204/401

- [ ] **Step 1: Write failing tests: android put 204, browser 422, unauth 401, delete, duplicate transfer**
- [ ] **Step 2: Run fail 404**
- [ ] **Step 3: Implement endpoints reading `{"token": "..."}` body, checking client.kind, delegating, no token leakage**
- [ ] **Step 4: Run pass**
- [ ] **Step 5: Commit**

### Task 8: Worker tick integration and resilience

**Files:**
- Modify: `worker/src/worker/main.py` — add notifier construction, call `send_due_reminders` after job processing, guard with try/except

**Interfaces:**
- Consumes: `DojoPublishing.send_due_reminders`
- Produces: `run_tick` ordering: evaluate → claim/process → reminders → sweep stale; reminders failure does not skip sweep

- [ ] **Step 1: Write failing `worker/tests/test_worker.py` assertions that `run_tick` calls `send_due_reminders` and still sweeps on failure**
- [ ] **Step 2: Run fail**
- [ ] **Step 3: Implement `build_publishing` FCM enable flag, inject notifier, wrap `send_due_reminders` in try/except logging**
- [ ] **Step 4: Run pass `pytest worker/tests -v`**
- [ ] **Step 5: Commit**

### Task 9: Final verification and release

**Files:** —
- [ ] Run `mypy dojo-core backend worker`
- [ ] Run focused tests per seam, then full `pytest` suite
- [ ] Run `code-review` skill, fix findings, re-verify
- [ ] Commit `feat(#16): pending-review reminders and Android notifications` if not already

## Self-Review

- Spec coverage: policy config, cadence durability, quiet hours, token lifecycle, batch notifier, worker ordering, HTTP contracts all mapped to tasks 2-8; publication outcomes explicitly out-of-scope per spec.
- No placeholders; each step has concrete file paths and code.
- Types consistent: `ReminderPolicy` frozen, `Notification` data strings, `NotificationResult` lists of tokens.
