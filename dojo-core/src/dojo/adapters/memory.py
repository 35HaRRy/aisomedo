from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from threading import RLock
from typing import overload
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from dojo.exceptions import ConsentPolicyChanged, NoConsentPolicy
from dojo.model import (
    AuditEvent,
    Client,
    ConsentAcceptance,
    ConsentPolicy,
    Job,
    MetaCandidate,
    MetaConnectionStatus,
    Package,
    PairingCode,
    PushRegistration,
    Upload,
    YayinIncelemesi,
    YayinZamani,
)
from dojo.monitoring_models import (
    DELIVERY_COMPLETE,
    DELIVERY_PENDING,
    DELIVERY_SKIPPED,
    DISK_OPENED,
    DISK_RECOVERED,
    DeliveryLease,
    DeliveryOutcome,
    DiskSample,
    OperationalAlert,
    disk_event_key,
    disk_low_alert,
    disk_recovered_alert,
    job_failure_alert,
    job_failure_event_key,
    retry_delay_seconds,
    token_fingerprint,
)
from dojo.package_cleanup import owns_record


@dataclass
class _DeliveryState:
    """One recipient's attempts for one alert; mirrors ``operational_deliveries``."""

    delivery_id: int
    alert_id: str
    client_id: int
    status: str
    attempts: int
    due_at: datetime
    token_fingerprint: str | None = None
    claim_id: str | None = None
    lease_expires_at: datetime | None = None


class InMemoryStore:
    def __init__(self) -> None:
        self._packages: list[Package] = []
        self._events: list[AuditEvent] = []
        self._codes: list[PairingCode] = []
        self._clients: list[Client] = []
        self._client_hashes: dict[int, str] = {}
        self._next_id = 1
        self._next_code_id = 1
        self._next_client_id = 1
        self._next_event_id = 1
        self._policies: list[ConsentPolicy] = []
        self._acceptances: list[ConsentAcceptance] = []
        self._next_policy_id = 1
        self._next_acceptance_id = 1
        self._consent_lock = RLock()
        self._uploads: list[Upload] = []
        self._jobs: list[Job] = []
        self._settings: dict[str, object] = {}
        self._next_upload_id = 1
        self._next_job_id = 1
        self._occurrences: list[YayinZamani] = []
        self._next_occ_id = 1
        self._reviews: list[YayinIncelemesi] = []
        self._next_review_id = 1
        self._push_regs: dict[int, PushRegistration] = {}
        self._push_by_token: dict[str, int] = {}
        self._meta_conn: MetaConnectionStatus | None = None
        self._meta_enc_token: str | None = None
        self._meta_expires_at: datetime | None = None
        self._meta_attempts: dict[str, dict] = {}
        self._meta_lock = RLock()
        self._alerts: list[OperationalAlert] = []
        self._alert_recipients_at: dict[str, datetime] = {}
        self._deliveries: list[_DeliveryState] = []
        self._next_delivery_id = 1
        self._incidents: dict[str, str | None] = {}
        self._last_sampled_at: dict[str, datetime | None] = {}
        self._failure_generations: dict[int, int] = {}
        self._monitoring_lock = RLock()
        self._creation_lock = RLock()
        self._package_lock = RLock()
        self._emission_active: ContextVar[bool] = ContextVar("emission_active", default=False)

    @contextmanager
    def package_lock(self, *, wait: bool = True) -> Iterator[bool]:
        acquired = self._package_lock.acquire(blocking=wait)
        try:
            yield acquired
        finally:
            if acquired:
                self._package_lock.release()

    def package_work(self, package: Package) -> tuple[list[Upload], list[Job]]:
        uploads = [u for u in self._uploads if u.package_id == package.id]
        pks = {u.id for u in uploads}
        jobs = [j for j in self._jobs if j.upload_id in pks
                or j.payload.get("package") == package.folder_name]
        return uploads, jobs

    def delete_package_records(self, package: Package, media_ids: set[str]) -> None:
        uploads, jobs = self.package_work(package)
        upload_ids, job_ids = {u.upload_id for u in uploads}, {j.job_id for j in jobs}
        review_ids = {r.id for r in self._reviews if r.package_folder == package.folder_name}
        self._events = [e for e in self._events if not owns_record(
            e.details, package.folder_name, upload_ids, job_ids, media_ids, review_ids,
        )]
        self._reviews = [r for r in self._reviews if r.id not in review_ids]
        alert_ids = {a.alert_id for a in self._alerts if a.data.get("job_id") in job_ids}
        self._alerts = [a for a in self._alerts if a.alert_id not in alert_ids]
        self._deliveries = [d for d in self._deliveries if d.alert_id not in alert_ids]
        for alert_id in alert_ids:
            self._alert_recipients_at.pop(alert_id, None)
        for job in jobs:
            self._failure_generations.pop(job.id, None)
        self._jobs = [j for j in self._jobs if j.job_id not in job_ids]
        self._uploads = [u for u in self._uploads if u.upload_id not in upload_ids]
        self._packages = [p for p in self._packages if p.id != package.id]

    @contextmanager
    def emission_transaction(self) -> Iterator[None]:
        """Single-process test adapter: no persistence rollback or distributed lock."""
        if self._emission_active.get():
            raise RuntimeError("nested emission transactions are not supported")
        token = self._emission_active.set(True)
        try:
            yield
        finally:
            self._emission_active.reset(token)

    def try_advisory_xact_lock(self, key: int) -> bool:
        if not self._emission_active.get():
            raise RuntimeError("advisory lock requires an emission transaction")
        return True

    @overload
    def create(self, obj: Package) -> Package: ...
    @overload
    def create(self, obj: Upload) -> Upload: ...
    @overload
    def create(self, obj: Job) -> Job: ...
    @overload
    def create(self, obj: YayinZamani) -> YayinZamani: ...
    @overload
    def create(self, obj: YayinIncelemesi) -> YayinIncelemesi: ...

    def create(
        self, obj: Package | Upload | Job | YayinZamani | YayinIncelemesi
    ) -> Package | Upload | Job | YayinZamani | YayinIncelemesi:
        if isinstance(obj, YayinIncelemesi):
            # Parity with PostgresStore.create: duplicates raise; use
            # create_review_once for race-safe insertion.
            if (
                self.get_by_occurrence_revision(
                    obj.occurrence_id, obj.revision_digest,
                )
                is not None
            ):
                raise IntegrityError(
                    "INSERT INTO yayin_incelemesi", {}, Exception("duplicate review"),
                )
            return self.create_review_once(obj)[0]
        if isinstance(obj, YayinZamani):
            with self._creation_lock:
                if obj.kind == "regular":
                    for existing in self._occurrences:
                        if existing.kind == "regular" and existing.due_at == obj.due_at:
                            return existing
                created_occ = replace(obj, id=self._next_occ_id)
                self._next_occ_id += 1
                self._occurrences.append(created_occ)
                return created_occ
        if isinstance(obj, Upload):
            created_upload = replace(obj, id=self._next_upload_id)
            self._next_upload_id += 1
            self._uploads.append(created_upload)
            return created_upload
        if isinstance(obj, Job):
            # Parity with PostgresStore.create: duplicate job_id raises; use
            # create_job_once for race-safe insertion.
            for candidate in self._jobs:
                if candidate.job_id == obj.job_id:
                    raise IntegrityError(
                        "INSERT INTO jobs", {}, Exception("duplicate job"),
                    )
            return self.create_job_once(obj)[0]
        created_package = replace(obj, id=self._next_id)
        self._next_id += 1
        self._packages.append(created_package)
        return created_package

    def create_job_once(
        self, job: Job, *, audit: AuditEvent | None = None,
    ) -> tuple[Job, bool]:
        with self._creation_lock:
            if job.kind == "render" and job.status in ("queued", "processing"):
                for existing in self._jobs:
                    if (existing.kind == "render"
                            and existing.status in ("queued", "processing")
                            and existing.payload.get("package") == job.payload.get("package")
                            and existing.payload.get("digest") == job.payload.get("digest")):
                        return existing, False
            created = replace(job, id=self._next_job_id)
            if audit is not None:
                self.append(audit)
            self._next_job_id += 1
            self._jobs.append(created)
            return created, True

    def create_review_once(
        self, review: YayinIncelemesi, *, audit: AuditEvent | None = None,
    ) -> tuple[YayinIncelemesi, bool]:
        with self._creation_lock:
            existing = self.get_by_occurrence_revision(
                review.occurrence_id, review.revision_digest,
            )
            if existing is not None:
                return existing, False
            created = replace(review, id=self._next_review_id)
            if audit is not None:
                self.append(replace(audit, details={**audit.details, "review_id": created.id}))
            self._next_review_id += 1
            self._reviews.append(created)
            return created, True

    def get_active(self) -> Package | None:
        for package in reversed(self._packages):
            if package.status == "active":
                return package
        return None

    def list_completed(self) -> list[Package]:
        return [p for p in self._packages if p.status == "completed"]

    def get_publishing(self) -> Package | None:
        for package in reversed(self._packages):
            if package.status == "publishing":
                return package
        return None

    def get_by_folder(self, folder_name: str) -> Package | None:
        return next((p for p in self._packages if p.folder_name == folder_name), None)

    @overload
    def update(self, obj: Package) -> Package: ...
    @overload
    def update(self, obj: Upload) -> Upload: ...
    @overload
    def update(self, obj: Job) -> Job: ...
    @overload
    def update(self, obj: YayinZamani) -> YayinZamani: ...
    @overload
    def update(self, obj: YayinIncelemesi) -> YayinIncelemesi: ...

    def update(
        self, obj: Package | Upload | Job | YayinZamani | YayinIncelemesi
    ) -> Package | Upload | Job | YayinZamani | YayinIncelemesi:
        if isinstance(obj, Upload):
            for i, existing_upload in enumerate(self._uploads):
                if existing_upload.id == obj.id:
                    self._uploads[i] = obj
                    return obj
            raise ValueError(f"upload {obj.id} not found")
        if isinstance(obj, Job):
            for i, existing_job in enumerate(self._jobs):
                if existing_job.id == obj.id:
                    # Only the first nonfailed -> failed transition emits; the
                    # generation lives here so the domain Job stays unchanged.
                    if existing_job.status != "failed" and obj.status == "failed":
                        self._record_job_failure(obj)
                    self._jobs[i] = obj
                    return obj
            raise ValueError(f"job {obj.id} not found")
        if isinstance(obj, YayinZamani):
            for i, existing_occ in enumerate(self._occurrences):
                if existing_occ.id == obj.id:
                    self._occurrences[i] = obj
                    return obj
            raise ValueError(f"occurrence {obj.id} not found")
        if isinstance(obj, YayinIncelemesi):
            for i, existing_review in enumerate(self._reviews):
                if existing_review.id == obj.id:
                    self._reviews[i] = obj
                    return obj
            raise ValueError(f"review {obj.id} not found")
        for i, existing_package in enumerate(self._packages):
            if existing_package.id == obj.id:
                self._packages[i] = obj
                return obj
        raise ValueError(f"package {obj.id} not found")

    def append(self, event: AuditEvent) -> None:
        stored = replace(event, id=self._next_event_id)
        self._next_event_id += 1
        self._events.append(stored)

    def list_recent(self, limit: int = 50, before_id: int | None = None) -> list[AuditEvent]:
        events = self._events
        if before_id is not None:
            events = [e for e in events if e.id < before_id]
        return list(reversed(events[-limit:]))

    def create_code(self, code: PairingCode) -> PairingCode:
        created = replace(code, id=self._next_code_id)
        self._next_code_id += 1
        self._codes.append(created)
        return created

    def find_code_by_hash(self, code_hash: str) -> PairingCode | None:
        return next((c for c in self._codes if c.code_hash == code_hash), None)

    def mark_code_consumed(self, code_id: int, at: datetime) -> bool:
        for i, code in enumerate(self._codes):
            if code.id == code_id and code.consumed_at is None:
                self._codes[i] = replace(code, consumed_at=at)
                return True
        return False

    def find_client_by_id(self, client_id: int) -> Client | None:
        return next((c for c in self._clients if c.id == client_id), None)

    def create_client(self, client: Client, credential_hash: str) -> Client:
        created = replace(client, id=self._next_client_id)
        self._next_client_id += 1
        self._client_hashes[created.id] = credential_hash
        self._clients.append(created)
        return created

    def find_client_by_credential_hash(self, credential_hash: str) -> Client | None:
        for client in self._clients:
            if self._client_hashes.get(client.id) == credential_hash:
                return client
        return None

    def list_clients(self) -> list[Client]:
        return list(self._clients)

    def mark_client_revoked(self, client_id: int, at: datetime) -> None:
        for i, client in enumerate(self._clients):
            if client.id == client_id and client.revoked_at is None:
                self._clients[i] = replace(client, revoked_at=at)
                return

    def touch_client(self, client_id: int, at: datetime) -> None:
        for i, client in enumerate(self._clients):
            if client.id == client_id:
                self._clients[i] = replace(client, last_seen_at=at)
                return

    def create_policy(
        self, *, version: int, text: str, created_by: str, created_at: datetime
    ) -> ConsentPolicy:
        with self._consent_lock:
            return self._create_policy(
                version=version, text=text, created_by=created_by, created_at=created_at
            )

    def _create_policy(
        self, *, version: int, text: str, created_by: str, created_at: datetime
    ) -> ConsentPolicy:
        for i, existing in enumerate(self._policies):
            if existing.version == version:
                updated = replace(
                    existing,
                    text=text,
                    created_by=created_by,
                    created_at=created_at,
                )
                self._policies[i] = updated
                return updated
        created = ConsentPolicy(
            id=self._next_policy_id,
            version=version,
            text=text,
            created_by=created_by,
            created_at=created_at,
        )
        self._next_policy_id += 1
        self._policies.append(created)
        return created

    def get_current_policy(self) -> ConsentPolicy | None:
        return max(self._policies, key=lambda p: p.version, default=None)

    def get_policy(self, version: int) -> ConsentPolicy | None:
        return next((p for p in self._policies if p.version == version), None)

    def find_acceptance(self, policy_version: int) -> ConsentAcceptance | None:
        return next((a for a in self._acceptances if a.policy_version == policy_version), None)

    def record_acceptance(self, acceptance: ConsentAcceptance) -> bool:
        with self._consent_lock:
            return self._record_acceptance(acceptance)

    def _record_acceptance(self, acceptance: ConsentAcceptance) -> bool:
        if any(a.policy_version == acceptance.policy_version for a in self._acceptances):
            return False
        created = replace(acceptance, id=self._next_acceptance_id)
        self._next_acceptance_id += 1
        self._acceptances.append(created)
        return True

    def accept_policy_version(
        self, *, client: Client, version: int | None, accepted_at: datetime
    ) -> tuple[ConsentAcceptance, bool]:
        with self._consent_lock:
            policy = self.get_current_policy()
            if policy is None:
                raise NoConsentPolicy("no consent policy configured")
            if version is not None and version != policy.version:
                raise ConsentPolicyChanged("consent policy changed; reload before accepting")
            existing = self.find_acceptance(policy.version)
            if existing is not None:
                return existing, False
            acceptance = ConsentAcceptance(
                policy_version=policy.version, accepted_at=accepted_at,
                accepting_client_id=client.id, accepting_client_name=client.name,
                accepting_client_kind=client.kind,
            )
            self.record_acceptance(acceptance)
            recorded = self.find_acceptance(policy.version)
            assert recorded is not None
            return recorded, True

    @overload
    def get(self, key: str) -> Upload | None: ...
    @overload
    def get(self, key: str) -> Job | None: ...  # type: ignore[overload-cannot-match]
    @overload
    def get(self, key: str) -> object | None: ...  # type: ignore[overload-cannot-match]
    @overload
    def get(self, key: int) -> YayinIncelemesi | None: ...

    def get(self, key: str | int) -> Upload | Job | object | YayinIncelemesi | None:
        if isinstance(key, int):
            return next((r for r in self._reviews if r.id == key), None)
        for u in self._uploads:
            if u.upload_id == key:
                return u
        for j in self._jobs:
            if j.job_id == key:
                return j
        return self._settings.get(key)

    def get_by_pk(self, upload_pk: int | None) -> Upload | None:
        if upload_pk is None:
            return None
        return next((u for u in self._uploads if u.id == upload_pk), None)

    def list_active(self) -> list[Upload]:
        return [u for u in self._uploads if u.status in ("receiving", "queued", "processing")]

    def list_stale(self, cutoff: datetime) -> list[Upload]:
        return [
            u
            for u in self._uploads
            if u.status in ("receiving", "queued", "conflict") and u.updated_at < cutoff
        ]

    def list_conflicts(self, package_id: int) -> list[Upload]:
        return [
            u for u in self._uploads if u.status == "conflict" and u.package_id == package_id
        ]

    def get_by_upload(self, upload_pk: int) -> Job | None:
        return next((j for j in self._jobs if j.upload_id == upload_pk), None)

    def claim_next(self, claimed_at: datetime) -> Job | None:
        for i, job in enumerate(self._jobs):
            if job.status == "queued":
                claimed = replace(job, status="processing", claimed_at=claimed_at)
                self._jobs[i] = claimed
                return claimed
        return None

    def set(self, key: str, value: object, *, updated_at: datetime) -> None:
        self._settings[key] = value

    def max_regular_due_at(self) -> datetime | None:
        dates = [o.due_at for o in self._occurrences if o.kind == "regular"]
        return max(dates) if dates else None

    def prune_regular_future(self, now: datetime) -> int:
        kept = [o for o in self._occurrences if not (o.kind == "regular" and o.due_at > now)]
        removed = len(self._occurrences) - len(kept)
        self._occurrences = kept
        return removed

    def has_regular_at(self, due_at: datetime) -> bool:
        return any(o.kind == "regular" and o.due_at == due_at for o in self._occurrences)

    def has_pending_manual(self) -> bool:
        return any(o.kind == "manual" and o.status == "pending" for o in self._occurrences)

    def list_due(self, now: datetime) -> list[YayinZamani]:
        return [
            o for o in self._occurrences
            if o.status == "pending" and o.due_at <= now
        ]

    def list_all(self) -> list[YayinZamani]:
        return list(self._occurrences)

    def next_regular_after(self, now: datetime) -> YayinZamani | None:
        candidates = [
            o for o in self._occurrences
            if o.kind == "regular" and o.status == "pending" and o.due_at > now
        ]
        return min(candidates, key=lambda o: o.due_at, default=None)

    def get_by_occurrence_revision(
        self, occurrence_id: int, revision_digest: str
    ) -> YayinIncelemesi | None:
        return next(
            (
                r
                for r in self._reviews
                if r.occurrence_id == occurrence_id
                and r.revision_digest == revision_digest
            ),
            None,
        )

    def list_pending(self) -> list[YayinIncelemesi]:
        return [r for r in self._reviews if r.status == "pending"]

    def resolve_if_pending(
        self,
        review_id: int,
        version: int,
        status: str,
        resolved_at: datetime,
        resolved_by: str | None,
    ) -> YayinIncelemesi | None:
        for i, review in enumerate(self._reviews):
            if review.id == review_id and review.status == "pending" and review.version == version:
                updated = replace(
                    review,
                    status=status,
                    version=review.version + 1,
                    resolved_at=resolved_at,
                    resolved_by=resolved_by,
                )
                self._reviews[i] = updated
                return updated
        return None

    def update_last_reminded_at(self, review_id: int, at: datetime) -> YayinIncelemesi | None:
        for i, review in enumerate(self._reviews):
            if review.id == review_id:
                updated = replace(review, last_reminded_at=at)
                self._reviews[i] = updated
                return updated
        return None

    def register_token(self, client_id: int, token: str, at: datetime) -> PushRegistration:
        # transfer if token already owned
        with self._monitoring_lock:
            owner = self._push_by_token.get(token)
            if owner is not None and owner != client_id:
                self._push_regs.pop(owner, None)
            # remove old token for this client if different
            old = self._push_regs.get(client_id)
            if old is not None and old.token != token:
                self._push_by_token.pop(old.token, None)
            reg = PushRegistration(client_id=client_id, token=token, updated_at=at)
            self._push_regs[client_id] = reg
            self._push_by_token[token] = client_id
            return reg

    def remove_by_client(self, client_id: int) -> None:
        with self._monitoring_lock:
            reg = self._push_regs.pop(client_id, None)
            if reg is not None:
                self._push_by_token.pop(reg.token, None)

    def remove_by_token(self, token: str) -> None:
        with self._monitoring_lock:
            owner = self._push_by_token.pop(token, None)
            if owner is not None:
                self._push_regs.pop(owner, None)

    def list_active_device_tokens(self) -> list[PushRegistration]:
        active: list[PushRegistration] = []
        with self._monitoring_lock:
            for reg in list(self._push_regs.values()):
                client = self.find_client_by_id(reg.client_id)
                if client is None or client.revoked_at is not None:
                    continue
                if client.kind != "device":
                    continue
                active.append(reg)
        return active

    # Operational monitoring
    @property
    def recorded_alerts(self) -> list[OperationalAlert]:
        """Recorded alerts in creation order, for contract tests."""
        with self._monitoring_lock:
            return list(self._alerts)

    def _record_job_failure(self, job: Job) -> None:
        with self._monitoring_lock:
            generation = self._failure_generations.get(job.id, 0) + 1
            self._failure_generations[job.id] = generation
            self._alerts.append(job_failure_alert(
                alert_id=str(uuid4()),
                event_key=job_failure_event_key(job.job_id, generation),
                job_id=job.job_id,
                kind=job.kind,
                created_at=job.finished_at or job.created_at,
            ))

    def record_disk_sample(
        self, sample: DiskSample, *, low_percent: float, recovery_percent: float,
    ) -> None:
        free_percent = sample.free_percent
        with self._monitoring_lock:
            last = self._last_sampled_at.get(sample.target)
            if last is not None and sample.sampled_at <= last:
                return  # Stale or repeated reading: cannot open or close anything.
            self._last_sampled_at[sample.target] = sample.sampled_at
            incident_id = self._incidents.get(sample.target)
            if incident_id is None:
                if free_percent < low_percent:
                    incident_id = str(uuid4())
                    self._incidents[sample.target] = incident_id
                    self._alerts.append(disk_low_alert(
                        alert_id=str(uuid4()),
                        event_key=disk_event_key(sample.target, incident_id, DISK_OPENED),
                        target=sample.target,
                        created_at=sample.sampled_at,
                    ))
            elif free_percent >= recovery_percent:
                self._incidents[sample.target] = None
                self._alerts.append(disk_recovered_alert(
                    alert_id=str(uuid4()),
                    event_key=disk_event_key(sample.target, incident_id, DISK_RECOVERED),
                    target=sample.target,
                    created_at=sample.sampled_at,
                ))

    def prepare_alert_deliveries(self, now: datetime, *, limit: int = 100) -> int:
        with self._monitoring_lock:
            recipients = self.list_active_device_tokens()
            if not recipients:
                return 0  # No recipient is not a delivery: alerts stay pending.
            unsnapshotted = [
                alert for alert in self._alerts if alert.alert_id not in self._alert_recipients_at
            ][:limit]
            for alert in unsnapshotted:
                # One snapshot for the whole batch: devices paired after this
                # point are not historical recipients of these alerts.
                for registration in recipients:
                    self._deliveries.append(_DeliveryState(
                        delivery_id=self._next_delivery_id,
                        alert_id=alert.alert_id,
                        client_id=registration.client_id,
                        status=DELIVERY_PENDING,
                        attempts=0,
                        due_at=now,
                    ))
                    self._next_delivery_id += 1
                self._alert_recipients_at[alert.alert_id] = now
            return len(unsnapshotted)

    def claim_alert_delivery(
        self, now: datetime, *, lease_seconds: int = 60,
    ) -> DeliveryLease | None:
        with self._monitoring_lock:
            candidates = sorted(
                (
                    delivery for delivery in self._deliveries
                    if delivery.status == DELIVERY_PENDING
                    and delivery.due_at <= now
                    and (delivery.claim_id is None
                         or (delivery.lease_expires_at is not None
                             and delivery.lease_expires_at <= now))
                ),
                key=lambda delivery: (delivery.due_at, delivery.delivery_id),
            )
            for delivery in candidates:
                registration = self._current_registration(delivery.client_id)
                if registration is None:
                    # Revoked, de-paired or non-device recipients are terminal:
                    # resending to them can only fail forever.
                    delivery.status = DELIVERY_SKIPPED
                    delivery.claim_id = None
                    delivery.lease_expires_at = None
                    continue
                claim_id = str(uuid4())
                delivery.claim_id = claim_id
                delivery.attempts += 1
                delivery.token_fingerprint = token_fingerprint(registration.token)
                delivery.lease_expires_at = now + timedelta(seconds=lease_seconds)
                alert = next(a for a in self._alerts if a.alert_id == delivery.alert_id)
                return DeliveryLease(
                    delivery_id=delivery.delivery_id,
                    claim_id=claim_id,
                    alert=alert,
                    client_id=delivery.client_id,
                    token=registration.token,
                    attempt=delivery.attempts,
                )
            return None

    def _current_registration(self, client_id: int) -> PushRegistration | None:
        """The registration a claim may use, rechecked for revocation."""
        registration = self._push_regs.get(client_id)
        if registration is None:
            return None
        client = self.find_client_by_id(client_id)
        if client is None or client.revoked_at is not None or client.kind != "device":
            return None
        return registration

    def finish_alert_delivery(
        self, lease: DeliveryLease, *, outcome: DeliveryOutcome, now: datetime,
    ) -> bool:
        with self._monitoring_lock:
            delivery = next(
                (d for d in self._deliveries if d.delivery_id == lease.delivery_id), None,
            )
            if (
                delivery is None
                or delivery.status != DELIVERY_PENDING
                or delivery.claim_id != lease.claim_id
                or delivery.lease_expires_at is None
                or delivery.lease_expires_at <= now
            ):
                return False
            delivery.claim_id = None
            delivery.lease_expires_at = None
            if outcome == "accepted":
                delivery.status = DELIVERY_COMPLETE
            else:
                delivery.status = DELIVERY_PENDING
                delivery.due_at = now + timedelta(
                    seconds=retry_delay_seconds(delivery.attempts)
                )
                if outcome == "invalid":
                    # Delete exactly the token that was used: a registration that
                    # has since rotated must survive and stay deliverable.
                    current = self._push_regs.get(lease.client_id)
                    if current is not None and current.token == lease.token:
                        self.remove_by_token(lease.token)
            return True

    # Meta connection store
    def get_meta_status(self) -> MetaConnectionStatus | None:
        with self._meta_lock:
            return self._meta_conn

    def get_active_snapshot(self) -> tuple[MetaConnectionStatus, str] | None:
        with self._meta_lock:
            if self._meta_conn is None or self._meta_enc_token is None:
                return None
            return self._meta_conn, self._meta_enc_token

    def upsert_active(
        self,
        *,
        ig_user_id: str,
        ig_username: str,
        page_id: str | None,
        page_name: str | None,
        encrypted_token: str,
        token_expires_at: datetime | None,
        health: str,
        last_checked_at: datetime | None,
        last_refreshed_at: datetime | None,
        last_error: str | None,
        connection_type: str = "facebook_login",
    ) -> MetaConnectionStatus:
        with self._meta_lock:
            self._meta_enc_token = encrypted_token
            self._meta_expires_at = token_expires_at
            self._meta_conn = MetaConnectionStatus(
                health=health,
                ig_user_id=ig_user_id,
                ig_username=ig_username,
                page_id=page_id,
                page_name=page_name,
                expires_at=token_expires_at,
                last_checked_at=last_checked_at,
                last_refreshed_at=last_refreshed_at,
                last_error=last_error,
                connection_type=connection_type,
            )
            return self._meta_conn

    def get_raw_active(self) -> tuple[str, datetime | None] | None:
        with self._meta_lock:
            if self._meta_enc_token:
                return self._meta_enc_token, self._meta_expires_at
            return None

    def update_health(
        self, health: str, last_checked_at: datetime | None, last_error: str | None,
        *, expected_encrypted_token: str | None = None,
    ) -> MetaConnectionStatus | None:
        with self._meta_lock:
            if self._meta_conn is None:
                return None
            if (expected_encrypted_token is not None
                    and self._meta_enc_token != expected_encrypted_token):
                return None
            self._meta_conn = replace(
                self._meta_conn, health=health,
                last_checked_at=last_checked_at, last_error=last_error,
            )
            return self._meta_conn

    def update_token(
        self, encrypted_token: str, token_expires_at: datetime, last_refreshed_at: datetime,
        *, expected_encrypted_token: str | None = None,
    ) -> MetaConnectionStatus | None:
        with self._meta_lock:
            if self._meta_conn is None:
                return None
            if (expected_encrypted_token is not None
                    and self._meta_enc_token != expected_encrypted_token):
                return None
            self._meta_enc_token = encrypted_token
            self._meta_expires_at = token_expires_at
            self._meta_conn = replace(
                self._meta_conn, expires_at=token_expires_at, last_refreshed_at=last_refreshed_at,
            )
            return self._meta_conn

    def get_meta_attempt(self, attempt_id: str) -> dict | None:
        return self._meta_attempts.get(attempt_id)

    def find_attempt_by_state_hash(self, state_hash: str) -> dict | None:
        for rec in self._meta_attempts.values():
            if rec.get("state_hash") == state_hash:
                return rec
        return None

    def create_attempt(self, attempt: dict) -> dict:
        self._meta_attempts[attempt["id"]] = attempt
        return attempt

    def mark_attempt_completed(
        self,
        attempt_id: str,
        candidates: list[MetaCandidate],
        encrypted_temp_token: str | None,
        temp_token_expires_at: datetime | None,
    ) -> None:
        rec = self._meta_attempts.get(attempt_id)
        if rec is None:
            return
        rec["status"] = "completed"
        rec["candidates"] = [c.to_dict() if hasattr(c, "to_dict") else c for c in candidates]
        rec["encrypted_temp_token"] = encrypted_temp_token
        rec["temp_token_expires_at"] = temp_token_expires_at

    def mark_attempt_failed(self, attempt_id: str, error: str) -> None:
        rec = self._meta_attempts.get(attempt_id)
        if rec is None:
            return
        rec["status"] = "failed"
        rec["last_error"] = error

    def consume_attempt(self, attempt_id: str) -> dict | None:
        rec = self._meta_attempts.pop(attempt_id, None)
        return rec
