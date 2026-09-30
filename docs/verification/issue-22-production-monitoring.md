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
delivery) are not met; see [Unmet acceptance criteria](#unmet-acceptance-criteria).

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
| `verification_python` | 3.14.6 via `.venv` |

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

Skip detail: the 2 dojo-core skips are `ffmpeg unavailable`
(`tests/test_media_processor.py:113` and `:142`) — environment-gated, unrelated
to monitoring, not failures.

### 3.2 Acceptance criteria covered by automated tests

| # | Spec criterion (`Verification and completion`) | Test files | Result |
|---|---|---|---|
| C1 | Backend readiness fails on unavailable database and recovers when restored | `backend/tests/test_health.py` (`test_ready_exception_maps_to_503_with_redacted_body`, `test_ready_recovers_when_probe_recovers`, `test_readiness_engine_timeout_budget`, `test_readiness_check_false_on_unreachable_database`) | `VERIFIED` |
| C2 | Worker probes reject stale/corrupt state; accept long work within the busy deadline; a stuck operation eventually fails the probe | `worker/tests/test_health.py` (`test_missing_record_is_unhealthy`, `test_corrupt_record_is_unhealthy`, `test_wrong_boot_id_is_unhealthy`, `test_stopped_phase_is_unhealthy`, `test_idle_boundary_119_healthy_120_not`, `test_busy_boundary_121_healthy_3600_not`, `test_blocked_tick_cannot_renew_busy_deadline`, `test_cli_main_exits_0_healthy_1_stale`) | `VERIFIED` |
| C3 | Web health checks exercise built assets in both production proxy modes | `ops/verify-monitoring.sh` phase H (real Caddy + synthetic API proxy, both modes, asset-removal → 404 not SPA fallback) — **not executed locally**, see C9 | `PENDING` |
| C4 | JSON logs parse and sensitive test values never appear in captured output | `dojo-core/tests/test_observability.py` (`test_message_text_is_never_serialized`, `test_secrets_never_reach_the_output`, `test_only_allowlisted_extras_are_serialized`, `test_access_record_keeps_method_status_and_drops_query`, `test_unexpected_exception_keeps_class_and_frames_only`) plus the log assertions in `ops/verify-monitoring.sh` | `VERIFIED` (unit level) |
| C5 | Disk incident/recovery thresholds, restarts, bad samples, deduplication with deterministic clock and disk samples | `worker/tests/test_monitoring.py` (`test_low_target_opens_one_incident_and_alerts_once`, `test_hysteresis_holds_the_incident_open_between_thresholds`, `test_a_restart_while_still_low_opens_no_second_incident`, `test_one_failed_mount_never_reads_as_recovery_and_other_still_sample`, `test_a_rejected_sample_is_logged_and_never_escapes_the_turn`, `test_thresholds_must_keep_the_hysteresis_order`) | `VERIFIED` |
| C6 | Terminal failures create alerts even when job processing catches exceptions; repeated scans, concurrency, retries and crashes preserve delivery semantics | `dojo-core/tests/test_monitoring_failures.py` (`test_missing_staged_upload_persists_a_failed_job_and_alerts`, `test_rejected_render_persists_a_failed_job_and_alerts`, `test_repeated_updates_of_one_failure_do_not_duplicate_the_alert`, `test_an_unexpected_error_without_a_terminal_state_fabricates_nothing`) | `VERIFIED` |
| C7 | FCM tests cover partial failures, invalid/revoked registrations, no devices, retry backoff | `dojo-core/tests/test_monitoring_delivery.py` (`test_no_device_keeps_the_alert_pending_instead_of_counting_it_delivered`, `test_partial_failure_retries_only_the_unaccepted_recipient`, `test_revoked_device_is_skipped_without_sending`, `test_transport_exception_isolates_one_recipient_and_schedules_the_retry`, `test_backoff_doubles_and_caps`, `test_expired_lease_is_reclaimed_and_its_stale_acknowledgement_refused`, `test_lost_acknowledgement_redelivers_the_same_alert_and_tag`), `dojo-core/tests/test_fcm.py`, `worker/tests/test_fcm_wiring.py` | `VERIFIED` |
| C8 | Enabling real delivery without a usable project identity fails at startup | `worker/tests/test_fcm_wiring.py` (`test_fcm_enabled_without_any_project_id_fails_startup`, `test_an_empty_project_id_does_not_count_as_configured`, `test_google_cloud_project_stands_in_for_the_fcm_project_id`, `test_configuration_failure_fails_startup_instead_of_falling_back`), `dojo-core/tests/test_fcm.py` (`test_missing_project_id_fails_at_startup_not_on_the_first_send`, `test_unusable_credentials_fail_startup_instead_of_degrading`) | `VERIFIED` |

### 3.3 Acceptance criteria NOT covered by automated tests

These require the deployed stack, a real device, or an operator account.

| # | Criterion | Why no test | Status |
|---|---|---|---|
| C3 | Web health in both proxy modes | Needs a Linux host with a real gateway build; `ops/verify-monitoring.sh` is a shell/Docker script, not part of the pytest run | `PENDING` |
| C9 | Run the deployment verification scripts and validate the rendered production Compose | `ops/verify-prod.sh` / `ops/verify-monitoring.sh` build images and drive a live Docker project | `PENDING` (partial — see §3.4) |
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

`3.4c-lint_status` — **PRE-EXISTING FAILURES, not from #22's files.** On
`7e150b8`, `ruff check` reports 29 errors in dojo-core, 8 in backend and 1 in
worker, and `mypy dojo-core/src/dojo` reports 1 error
(`dojo-core/src/dojo/publishing.py:390`). Every finding is in a file outside
this issue's scope (`adapters/db.py`, `adapters/meta.py`, `model.py`,
`publishing.py`, `routes/pairing.py`, `worker/main.py:251`, `test_publication.py`,
`test_schema_init.py`). Running ruff on only the #22 monitoring/logging/FCM files
returns `All checks passed!`. `mypy` is clean for `backend/src/backend` and
`worker/src/worker`. Recorded as an observation for a separate issue; **not**
claimed as a #22 pass.

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
| `android_redelivery_replaces` | *(unset)* — see note | `PENDING` |
| `android_no_review_navigation` | *(unset)* — tapping opens the dashboard, never a review screen | `BLOCKED` |

`android_redelivery_replaces` note: this is **not deterministically reproducible
by an operator**. A worker restart does not redeliver (incident state is
durable, so no second alert is produced). Redelivery of the same `alert_id`
occurs only when a provider acceptance is lost before acknowledgement
(expired lease), which has no operator-side trigger. The code path is covered
by `dojo-core/tests/test_monitoring_delivery.py::test_lost_acknowledgement_redelivers_the_same_alert_and_tag`
(VERIFIED at code level). The field stays `PENDING` rather than being filled
with a simulated observation.

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
   Both the table row and the setup section now say so, and `3.4c` records the
   observed render failure.
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
   transport failure and recovery, the named evidence fields, the honest
   statement that a restart does **not** redeliver, and the reminder that
   `dumpsys notification` output can contain a push token.
9. **Cross-links** — §3 health statuses and §8 now point at this evidence
   record, so a runbook-only reader knows what has and has not been observed.

## 7. What closes #22

1. Deploy the stack, fill §4.1 and §4.2.
2. Provision the two hosted checks and run the drill; fill §4.4.
3. Land #32 and #36, pair a device, execute the four contract acceptance steps;
   fill §4.3.
4. Re-read this file and confirm no `PENDING`/`BLOCKED` row remains, then
   update the spec's "Verification and completion" outcome.

Until steps 2 and 3 are done, #22 must stay open: documentation that a monitor
*should* exist is not evidence that one does.
