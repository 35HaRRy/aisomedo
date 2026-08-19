from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import overload

from dojo.model import (
    AuditEvent,
    Client,
    ConsentAcceptance,
    ConsentPolicy,
    Job,
    Package,
    PairingCode,
    Upload,
    YayinZamani,
)


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
        self._uploads: list[Upload] = []
        self._jobs: list[Job] = []
        self._settings: dict[str, object] = {}
        self._next_upload_id = 1
        self._next_job_id = 1
        self._occurrences: list[YayinZamani] = []
        self._next_occ_id = 1

    @overload
    def create(self, obj: Package) -> Package: ...
    @overload
    def create(self, obj: Upload) -> Upload: ...
    @overload
    def create(self, obj: Job) -> Job: ...
    @overload
    def create(self, obj: YayinZamani) -> YayinZamani: ...

    def create(
        self, obj: Package | Upload | Job | YayinZamani
    ) -> Package | Upload | Job | YayinZamani:
        if isinstance(obj, YayinZamani):
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
            created_job = replace(obj, id=self._next_job_id)
            self._next_job_id += 1
            self._jobs.append(created_job)
            return created_job
        created_package = replace(obj, id=self._next_id)
        self._next_id += 1
        self._packages.append(created_package)
        return created_package

    def get_active(self) -> Package | None:
        for package in reversed(self._packages):
            if package.status == "active":
                return package
        return None

    def list_completed(self) -> list[Package]:
        return [p for p in self._packages if p.status == "completed"]

    @overload
    def update(self, obj: Package) -> Package: ...
    @overload
    def update(self, obj: Upload) -> Upload: ...
    @overload
    def update(self, obj: Job) -> Job: ...

    def update(self, obj: Package | Upload | Job) -> Package | Upload | Job:
        if isinstance(obj, Upload):
            for i, existing_upload in enumerate(self._uploads):
                if existing_upload.id == obj.id:
                    self._uploads[i] = obj
                    return obj
            raise ValueError(f"upload {obj.id} not found")
        if isinstance(obj, Job):
            for i, existing_job in enumerate(self._jobs):
                if existing_job.id == obj.id:
                    self._jobs[i] = obj
                    return obj
            raise ValueError(f"job {obj.id} not found")
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
        if any(a.policy_version == acceptance.policy_version for a in self._acceptances):
            return False
        created = replace(acceptance, id=self._next_acceptance_id)
        self._next_acceptance_id += 1
        self._acceptances.append(created)
        return True

    @overload
    def get(self, key: str) -> Upload | None: ...
    @overload
    def get(self, key: str) -> Job | None: ...  # type: ignore[overload-cannot-match]
    @overload
    def get(self, key: str) -> object | None: ...  # type: ignore[overload-cannot-match]

    def get(self, key: str) -> Upload | Job | object | None:
        for u in self._uploads:
            if u.upload_id == key:
                return u
        for j in self._jobs:
            if j.job_id == key:
                return j
        return self._settings.get(key)

    def get_by_pk(self, upload_pk: int) -> Upload | None:
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
