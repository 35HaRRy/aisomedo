# Issue #22 — lean production monitoring: verification record

Verification record for issue #22, "Dojo Reel Publishing MVP — production
monitoring" (Tasks 1-6 implemented, Task 7 is this evidence pass).

**This document records what was observed. It contains no fabricated values.**
Every acceptance criterion has a named evidence field and one of three
statuses:

| Status | Meaning |
|---|---|
| `VERIFIED` | Observed directly, with the observation named. |
| `PENDING` | A well-defined step that cannot run yet because a named input is missing. |
| `BLOCKED` | Cannot be attempted at all until a named open issue lands. |

**#22 stays OPEN.** Two required live criteria (hosted monitoring, Android
delivery) are not met; see [§2 Unmet acceptance criteria](#2-unmet-acceptance-criteria).

- Spec: [`docs/superpowers/specs/2026-09-29-lean-production-monitoring-design.md`](../superpowers/specs/2026-09-29-lean-production-monitoring-design.md)
- Plan: [`docs/superpowers/plans/2026-09-29-lean-production-monitoring.md`](../superpowers/plans/2026-09-29-lean-production-monitoring.md)
- Operator runbook: [`docs/rehberler/production-monitoring.md`](../rehberler/production-monitoring.md)
- Client contract: [`docs/contracts/operational-alerts.md`](../contracts/operational-alerts.md)

---

## 1. Verification identity

| Field | Value |
|---|---|
| `verified_at` | 2026-09-30 |
| `verified_on_commit` | `7e150b8` (`docs(ops): mark firebase project id required for monitoring`), branch `development` |
| `deployed_commit` | *(none — no deployed stack exists)* |
| `deployed_image_tags` | *(none)* |
| `origin_sanitized` | *(none — no public origin)* |
| `android_device_build` | *(none — no paired device)* |
| `monitor_provider` | *(none — no operator account)* |
| `monitor_account_owner` | *(none)* |
| `verification_host` | Windows 11 dev workstation, Docker 29.8.0 (Linux containers available) |
| `verification_python` | CPython **3.12.13** — the uv-managed `.venv` (`.python-version` = `3.12`; `.venv/pyvenv.cfg` `version_info = 3.12`). Confirmed with `.venv\Scripts\python.exe -V` and `uv run --project <pkg> python -V`, all three reporting `Python 3.12.13`. Every ruff/mypy/pytest number below came from `uv run --project <pkg>`, i.e. that interpreter |

## 2. Unmet acceptance criteria

These are the required live criteria. They are recorded as unmet, not skipped.

| Criterion | Status | Missing input | What closes it |
|---|---|---|---|
| Hosted HTTPS monitors exist and fire | `PENDING` | Public HTTPS origin, deployed stack, operator-owned hosted-monitor account | Operator provisions the two checks described in runbook §6 and records `monitor_*` fields plus the drill receipt |
| Hosted outage/recovery drill | `PENDING` | Same as above | Operator runs the controlled drill (runbook §6) and records `outage_detected_at`, `recovery_detected_at`, `outage_receipt` |
| Android operational-alert display | `BLOCKED` | #32 (pairing/shell), #36 (FCM receiver) | Both issues land, a device pairs, the four contract acceptance steps are observed |

## 3. Code verification (local, reproducible)

### 3.1 Test suites

Run on 2026-09-30 from `7e150b8`:

| Suite | Command | Result |
|---|---|---|
| dojo-core | `uv run --project dojo-core pytest dojo-core/tests` | **499 passed, 2 skipped** |
| backend | `uv run --project backend pytest backend/tests` | **107 passed** |
| worker | `uv run --project worker pytest worker/tests` | **133 passed** |

Skip detail: the 2 dojo-core skips are `test_video_transcoded_to_h264_aac`
(`tests/test_media_processor.py:115`) and `test_video_mov_accepted` (`:144`).
Both are guarded by two stacked marks — `@pytest.mark.skipif(not
_docker_available(), reason="docker unavailable")` and `@pytest.mark.skipif(not
_ffmpeg_available(), reason="ffmpeg unavailable")` — and `pytest -rs` reported
the **ffmpeg** reason on this host. Neither test touches monitoring; they are
environment-gated, not failures.

### 3.2 Acceptance criteria covered by automated tests

| # | Spec criterion (`Verification and completion`) | Test files | Result |
|---|---|---|---|
| C1 | Backend readiness fails on unavailable database and recovers when restored | `backend/tests/test_health.py` (`test_ready_exception_maps_to_503_with_redacted_body`, `test_ready_recovers_when_probe_recovers`, `test_readiness_engine_timeout_budget`, `test_readiness_check_false_on_unreachable_database`) | `VERIFIED` |
| C2 | Worker probes reject stale/corrupt state; accept long work within the busy deadline; a stuck operation eventually fails the probe | `worker/tests/test_health.py` (`test_missing_record_is_unhealthy`, `test_corrupt_record_is_unhealthy`, `test_wrong_boot_id_is_unhealthy`, `test_stopped_phase_is_unhealthy`, `test_idle_boundary_119_healthy_120_not`, `test_busy_boundary_121_healthy_3600_not`, `test_blocked_tick_cannot_renew_busy_deadline`, `test_cli_main_exits_0_healthy_1_stale`) | `VERIFIED` |
| C3 | Web health checks exercise built assets in both production proxy modes | `ops/verify-monitoring.sh` phase H (real Caddy + synthetic API proxy, both modes, asset-removal → 404 not SPA fallback) — **not executed locally**, see C9 | `PENDING` |
| C4 | JSON logs parse and sensitive test values never appear in captured output | `dojo-core/tests/test_observability.py` (`test_message_text_is_never_serialized`, `test_secrets_never_reach_the_output`, `test_only_allowlisted_extras_are_serialized`, `test_access_record_keeps_method_status_and_drops_query`, `test_unexpected_exception_keeps_class_and_frames_only`) | `VERIFIED` at unit level. The log assertions in `ops/verify-monitoring.sh` are **not** part of this row — that script was not run (C9) |
| C5 | Disk incident/recovery thresholds, restarts, bad samples, deduplication with deterministic clock and disk samples | `worker/tests/test_monitoring.py` (`test_low_target_opens_one_incident_and_alerts_once`, `test_hysteresis_holds_the_incident_open_between_thresholds`, `test_a_restart_while_still_low_opens_no_second_incident`, `test_one_failed_mount_never_reads_as_recovery_and_others_still_sample`, `test_a_rejected_sample_is_logged_and_never_escapes_the_turn`, `test_thresholds_must_keep_the_hysteresis_order`) | `VERIFIED` |
| C6 | Terminal failures create alerts even when job processing catches exceptions; repeated scans, concurrency, retries and crashes preserve delivery semantics | `dojo-core/tests/test_monitoring_failures.py` (`test_missing_staged_upload_persists_a_failed_job_and_alerts`, `test_rejected_render_persists_a_failed_job_and_alerts`, `test_repeated_updates_of_one_failure_do_not_duplicate_the_alert`, `test_an_unexpected_error_without_a_terminal_state_fabricates_nothing`) | `VERIFIED` |
| C7 | FCM tests cover partial failures, invalid/revoked registrations, no devices, retry backoff | `dojo-core/tests/test_monitoring_delivery.py` (`test_no_device_keeps_the_alert_pending_instead_of_counting_it_delivered`, `test_partial_failure_retries_only_the_unaccepted_recipient`, `test_revoked_device_is_skipped_without_sending`, `test_transport_exception_isolates_one_recipient_and_schedules_the_retry`, `test_backoff_doubles_and_caps`, `test_expired_lease_is_reclaimed_and_its_stale_acknowledgement_refused`, `test_lost_acknowledgement_redelivers_the_same_alert_and_tag`), `dojo-core/tests/test_fcm.py`, `worker/tests/test_fcm_wiring.py` | `VERIFIED` |
| C8 | Enabling real delivery without a usable project identity fails at startup | `worker/tests/test_fcm_wiring.py` (`test_fcm_enabled_without_any_project_id_fails_startup`, `test_an_empty_project_id_does_not_count_as_configured`, `test_google_cloud_project_stands_in_for_the_fcm_project_id`, `test_configuration_failure_fails_startup_instead_of_falling_back`), `dojo-core/tests/test_fcm.py` (`test_missing_project_id_fails_at_startup_not_on_the_first_send`, `test_unusable_credentials_fail_startup_instead_of_degrading`) | `VERIFIED` |

### 3.3 Acceptance criteria NOT covered by automated tests

These require the deployed stack, a real device, or an operator account.

| # | Criterion | Why no test | Status |
|---|---|---|---|
| C3 | Web health in both proxy modes | Needs a Linux host with a real gateway build; `ops/verify-monitoring.sh` is a shell/Docker script, not part of the pytest run | `PENDING` |
| C9 | Run the deployment verification scripts and validate the rendered production Compose | `ops/verify-prod.sh` / `ops/verify-monitoring.sh` build images and drive a live Docker project | `PENDING` — the Compose render half passed (§3.4), the two scripts did not run. CI's equivalent checks are red and predate #22 (§3.6) |
| C10 | All three health probes healthy on a deployed stack | Needs a deployment | `PENDING` |
| C11 | Synthetic disk/job alert received on a real Android device | Needs #32 + #36 + a paired device | `BLOCKED` |
| C12 | Hosted outage/recovery alert received | Needs an operator-hosted monitor account | `PENDING` |

### 3.4 What was verified locally without a deployment

`3.4a-rendered_compose_base` — **VERIFIED**. The three base renders from
`.github/workflows/ci.yml` all exit 0:

```
docker compose --env-file ops/.env.example -f ops/docker-compose.yml config -q
docker compose --env-file ops/.env.example -f ops/docker-compose.prod.yml \
  -f ops/docker-compose.dedicated.yml config -q
docker compose --env-file ops/.env.example -f ops/docker-compose.prod.yml \
  -f ops/docker-compose.existing-proxy.yml config -q
```

`3.4b-rendered_compose_monitoring` — **VERIFIED**. The monitoring override
renders in both proxy modes with a throwaway credential path and
`FCM_PROJECT_ID=ci-not-a-project` (render only; nothing started, no real
credential used).

`3.4c-monitoring_requires_project_id` — **VERIFIED**. With `FCM_PROJECT_ID`
absent, the render fails with the fixable message
`required variable FCM_PROJECT_ID is missing a value: set FCM_PROJECT_ID in
.env to the Firebase project id`. This confirms that `GOOGLE_CLOUD_PROJECT`,
although the worker code reads it as a fallback, does **not** satisfy the
Compose guard — the runbook setup steps were corrected for this (Task 7).

`3.4d-caddyfile_valid` — **VERIFIED**. `caddy validate` in `caddy:2-alpine`
against `ops/gateway/Caddyfile` → `Valid configuration`.

### 3.5 Lint and typecheck: not clean, but nothing outstanding is #22's

`3.5-lint_status` — **NOT CLEAN. What remains is pre-existing baseline debt,
not introduced by #22.**

At the Task 7 review point (`7e150b8`) `ruff check` reported **38 findings**
(dojo-core 29, backend 8, worker 1) and `mypy` reported **1 error**
(`dojo-core/src/dojo/publishing.py:390`, `dict-item`).

An earlier revision of this record claimed every finding was "in a file outside
this issue's scope". **That was wrong** and is corrected here. The precise
breakdown, established with `git blame -L <line>,<line> --porcelain` on each
finding:

| Bucket | Count | Detail |
|---|---|---|
| Introduced by a #22 commit — **now fixed** | 0 | Was 1: `dojo-core/tests/test_schema_init.py:108` `F841` unused `conn`, blamed to `70a7eca` (*fix(monitoring): prove failure-generation lock and redact lease tokens*). The unbound local was removed (`with engine.connect():`, no `as conn`); the assertion inside the block is unchanged, so the test's meaning is identical. Verified: `ruff check dojo-core/tests/test_schema_init.py` → `All checks passed!`; `pytest dojo-core/tests/test_schema_init.py -q` → **22 passed** |
| In a #22-modified file, on a line that predates #22 | 11 | `dojo-core/src/dojo/adapters/db.py` ×6 (lines 295, 323, 336, 339, 1254, 1644) blamed to `4281e5f` (#16) and `33d50a7` (#17); `dojo-core/src/dojo/adapters/meta.py` ×3 (lines 1, 52, 125) and `worker/src/worker/main.py:251` blamed to `33d50a7` (#17); `dojo-core/src/dojo/__init__.py:1` blamed to `7d7bc67` (#4) |
| In a file #22 never touched | 26 | `adapters/signed_urls.py` ×1, `adapters/stubs.py` ×2, `meta_connection.py` ×5, `model.py` ×2, `publishing.py` ×4, `tests/test_publication.py` ×2, `backend/deps.py` ×1, `backend/routes/meta.py` ×4, `backend/routes/pairing.py` ×3 |

Current state on this branch: `ruff check dojo-core/src dojo-core/tests`
reports **28** (down from 29), and `ruff check dojo-core/tests` reports only
the 2 pre-existing `test_publication.py` findings. **#22 now introduces zero
ruff findings.** The remaining 37 are pre-existing, belong to a separate issue,
and nothing here is claimed as a pass.

`mypy` is clean for `backend/src/backend` and `worker/src/worker` (18 and 4
source files). The single mypy error is in `publishing.py`, a file #22 never
touched.

### 3.6 CI has never run against #22 — and it is currently RED

`3.6-ci_status` — **OPEN, and it weakens every `VERIFIED` row above.**

`.github/workflows/ci.yml:17-24` runs the same `ruff check` and `mypy`
commands recorded in §3.5. The most recent run of the `ci` workflow is:

- run `36627729807` — <https://github.com/35HaRRy/aisomedo/actions/runs/36627729807>
- head `f2a1379` *"docs: plan production monitoring implementation"*, 2026-09-29 23:34 +0300
- conclusion: **failure**; jobs: `web` success, **`backend` failure** (step `Lint`),
  **`ops` failure** (step `docker compose --env-file ops/.env.example -f
  ops/docker-compose.yml config`)

Two facts follow, and both matter:

1. **CI is red.** It was already red *before* #22, on the lint step and on the
   base compose render.
2. **CI has never run against #22's code.** `git merge-base --is-ancestor
   f2a1379 b0c1f51` exits 0: the last CI head is an ancestor of `b0c1f51`, the
   first #22 commit. Every #22 commit is dated 2026-09-30; the last CI run is
   2026-09-29. So no CI result — green or red — exists for any #22 commit.

Consequence for this record: §3.5 is the **only** evidence of lint/type state
for #22, and it is a local run. The local `docker compose … config` runs in
§3.4a all exited 0, including the exact command CI's `ops` job failed on, which
means the CI `ops` failure is not reproduced on this host; that discrepancy is
unexplained, is **not** investigated here, and is left for a separate issue.

The `F841` that #22 did introduce is now fixed (§3.5), so what remains open on
this item is only the red run and the fact that it predates #22. Closing it
means pushing and recording the resulting CI run — including whether the
pre-existing `Lint` and `ops` failures still stand.

## 4. Live evidence fields (all currently empty)

To be filled only with observed values. Never record secrets, device tokens, or
`ops/.env` contents.

### 4.1 Deployment health

| Field | Value | Status |
|---|---|---|
| `health_backend_status` | *(unset)* | `PENDING` |
| `health_worker_status` | *(unset)* | `PENDING` |
| `health_gateway_status` | *(unset)* | `PENDING` |
| `log_sample_backend` | *(unset)* — sanitized JSON line, runbook §4 | `PENDING` |
| `log_sample_worker` | *(unset)* — sanitized JSON line, runbook §4 | `PENDING` |
| `log_sample_gateway` | *(unset)* — sanitized access-log line, runbook §4 | `PENDING` |

### 4.2 Operational alerts (FCM)

| Field | Value | Status |
|---|---|---|
| `disk_low_alert_observed` | *(unset)* | `PENDING` |
| `disk_recovery_alert_observed` | *(unset)* | `PENDING` |
| `failed_job_alert_observed` | *(unset)* | `PENDING` |
| `delivery_pending_when_no_devices` | *(unset)* — an alert with no paired device must stay pending, not "delivered" | `PENDING` |
| `transport_retry_recovery` | *(unset)* — see runbook §6 for the reproducible procedure | `PENDING` |

### 4.3 Android delivery (contract acceptance steps 1-4)

| Field | Value | Status |
|---|---|---|
| `android_foreground_display` | *(unset)* — Turkish title/body for `disk.low` | `BLOCKED` (#32, #36) |
| `android_background_display` | *(unset)* — same alert in the tray, app backgrounded/killed | `BLOCKED` |
| `android_tag_equals_alert_id` | *(unset)* — `alert_id` used as the notification tag | `BLOCKED` |
| `android_redelivery_replaces` | *(unset)* — see the note below for the trigger and the closure condition | `PENDING` |
| `android_no_review_navigation` | *(unset)* — tapping opens the dashboard, never a review screen | `BLOCKED` |

#### `android_redelivery_replaces` — trigger and closure

An earlier revision of this note said there was "no operator-side trigger".
That was too strong. There is one; it is simply **non-deterministic**, so it
cannot be relied on to produce a clean observation in one attempt.

- The delivery claim takes a lease: `claim_alert_delivery(now, lease_seconds=60)`
  (`dojo-core/src/dojo/adapters/db.py:1367`, mirrored in
  `dojo-core/src/dojo/monitoring_ports.py:45`), setting
  `lease_expires_at = now + 60s` (`db.py:1400`).
- The send and the acknowledgement are separate: `DojoMonitoring.deliver_pending`
  claims, sends, then calls `_acknowledge` (`dojo-core/src/dojo/monitoring.py:101-190`).
- So if the worker dies **after FCM accepted the message but before the
  acknowledgement commits**, the lease is orphaned. After 60 seconds another
  delivery pass reclaims it and re-sends the *same* alert with the *same*
  `alert_id`, which the client must render as a replacement, not a second
  notification. This is exactly
  `test_lost_acknowledgement_redelivers_the_same_alert_and_tag` and
  `test_expired_lease_is_reclaimed_and_its_stale_acknowledgement_refused`.
- A plain `docker compose … restart worker` does **not** do it: incident state
  is durable, so a restart produces no new alert and no new delivery. The kill
  must land inside the send→acknowledge window, which is short.

**Closure condition for this field (restated).** It is satisfied either by:

- a live observation of a reclaimed delivery, using the SIGKILL-during-send
  procedure in runbook §6, accepting that the window is narrow and may need
  several attempts; or
- an explicit, recorded decision that this criterion is satisfied **at code
  level only** by the two tests named above, with the non-deterministic
  operator trigger documented rather than faked.

It must not be closed by a simulated or assumed redelivery. Until one of those
two happens it stays `PENDING`, and §7 step 5 accounts for that.

### 4.4 Hosted monitors

| Field | Value | Status |
|---|---|---|
| `monitor_provider` | *(unset)* | `PENDING` |
| `monitor_web_health_id` | *(unset)* | `PENDING` |
| `monitor_web_health_url` | *(unset)* — expected: `https://<DOMAIN>/web-health.txt` | `PENDING` |
| `monitor_api_ready_id` | *(unset)* | `PENDING` |
| `monitor_api_ready_url` | *(unset)* — expected: `https://<DOMAIN>/ready` | `PENDING` |
| `monitor_interval_seconds` | *(unset)* — must be ≤ 300 | `PENDING` |
| `monitor_certificate_validation` | *(unset)* | `PENDING` |
| `monitor_body_assertion_verified` | *(unset)* — see runbook §6 pre-flight | `PENDING` |
| `monitor_notification_contact` | *(unset)* — provider's own channel, not VPS-hosted | `PENDING` |
| `outage_detected_at` | *(unset)* | `PENDING` |
| `recovery_detected_at` | *(unset)* | `PENDING` |
| `outage_receipt` | *(unset)* — channel and time the provider's own alert arrived | `PENDING` |

## 5. Provider capability research (informational, vendor-neutral)

The runbook requires four capabilities: body (keyword) assertion, certificate
validation, interval ≤ 5 minutes, and an independent notification channel. The
code depends on **none** of them — the checks are external HTTP GETs and no
provider name appears in the source.

One currently-available provider was researched from current documentation on
**2026-09-30** (ctx7 `/websites/betterstack_uptime`, plus the provider's own
pricing page) so the operator's choice is informed:

| Capability | Better Stack Uptime | Source |
|---|---|---|
| Request-body assertion | Supported: `monitor_type: keyword` with `required_keyword`; an incident is created if the keyword is absent | <https://betterstack.com/docs/uptime/api/update-an-existing-monitor>, <https://betterstack.com/docs/uptime/api-monitor> |
| Certificate validation | Supported: monitor attribute `verify_ssl` ("Verify SSL certificate validity") | <https://betterstack.com/docs/uptime/api/monitors-api-response-params> |
| Check interval | Satisfies ≤ 5 min: `check_frequency` in seconds, default 30, "must be at least the timeout value"; the pricing page lists a 30-second minimum frequency | same two pages + <https://betterstack.com/pricing> |
| Notification channels | `email`, `sms`, `call` (phone), `push`, `critical_alert`, plus `policy_id` escalation; Slack, MS Teams, Zapier, webhooks | <https://betterstack.com/docs/uptime/monitoring-start>, <https://betterstack.com/pricing> |
| Redirect handling | Controllable: `follow_redirects` — set `false` so an HTTP 308 cannot pass a check | update-monitor API page |
| Free tier | 10 monitors, Slack and e-mail alerts — sufficient for two checks | <https://betterstack.com/pricing> |
| SSL **expiry** alerting | Requires a paid plan; this is separate from validating the certificate during each check | <https://betterstack.com/docs/uptime/ssl-certificate-monitor> |

Two gotchas worth knowing before provisioning: if a `policy_id` is attached to
a monitor, the simple `call`/SMS/e-mail/push toggles are ignored — so either
define the escalation policy with the channel you want, or attach no policy.
And the body-assertion setting must be verified, not assumed: the runbook
pre-flight (`/olmayan-yol` returning SPA `200`) is what proves a status-only
monitor would have passed.

Nothing was provisioned, and no account was created. Selecting and paying for a
provider is operator work, not this task's.

## 6. Runbook gaps closed in this task

All in [`docs/rehberler/production-monitoring.md`](../rehberler/production-monitoring.md):

1. **Web-health expected body was wrong/incomplete** — the table said
   "body contains `ok`". The asset is exactly `dojo-web-ok`
   (`web/public/web-health.txt`). Corrected, and the `/ready` success body
   `{"status":"ok"}` plus the 503 `{"status":"unavailable"}` failure body were
   added.
2. **`FCM_PROJECT_ID` was missing from the FCM setup steps** (Task 6 review
   minor). An operator following the runbook would hit a Compose render
   failure. Steps 3-5 now cover reading the project id and writing both
   required variables.
3. **`GOOGLE_CLOUD_PROJECT` caveat** (Task 6 review minor). The settings table
   claimed it as an equivalent fallback. The code does read it, but the Compose
   `:?` guard only sees `FCM_PROJECT_ID`, so it does not satisfy the render.
   Both the table row and the setup section now say so, and
   `3.4c-monitoring_requires_project_id` records the observed render failure.
4. **Provider capability checklist** — four required capabilities, so a
   provider that lacks body assertions can be rejected on the spot.
5. **Verified provider example with source URLs and a date**, kept explicitly
   informational and vendor-neutral.
6. **Pre-flight before the outage drill** — including the explicit statement
   that an unknown path returns SPA `200`, which is *why* body assertion is
   mandatory; plus the asset-presence check.
7. **Exact evidence fields to record**, with the explicit "never record secrets
   or tokens" list.
8. **Android acceptance procedure** — how to raise a `disk.low` /
   `disk.recovered` alert by moving the thresholds instead of filling a disk
   (constraint `0 < low < recovery <= 100`), how to reproduce a transient
   transport failure and recovery, the named evidence fields, the accurate
   account of the 60-second delivery lease as the (non-deterministic) redelivery
   trigger, and the reminder that `dumpsys notification` output can contain a
   push token.
9. **Cross-links** — §3 health statuses and §8 now point at this evidence
   record, so a runbook-only reader knows what has and has not been observed.

## 7. What closes #22

1. Push and record the resulting CI run, so CI has executed against #22 for the
   first time; note whether the pre-existing `Lint` and `ops` failures still
   stand (§3.5, §3.6). The `F841` that #22 introduced is already fixed, so this
   step is no longer about #22's own code.
2. Deploy the stack, fill §4.1 and §4.2.
3. Provision the two hosted checks and run the drill; fill §4.4.
4. Land #32 and #36, pair a device, execute the four contract acceptance steps;
   fill §4.3.
5. Resolve `android_redelivery_replaces` — observe the lease-reclaim redelivery,
   or record the explicit "code-level only" decision described in §4.3. This
   criterion is satisfiable **either** way, so it is a decision, not a missing
   input.
6. Re-read this file and confirm no `PENDING`/`BLOCKED` row remains, then
   update the spec's "Verification and completion" outcome.

Step 6 is not a demand for a fabricated observation: every row must reach
`VERIFIED` through an input that actually exists, or through the recorded
code-level decision described in step 5. If an input is still missing, the row
stays `PENDING`/`BLOCKED` and #22 stays open — that is the correct outcome, not
a failure of this document.

Until steps 2 and 3 are done, #22 must stay open: documentation that a monitor
*should* exist is not evidence that one does.
