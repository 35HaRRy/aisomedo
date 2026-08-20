from __future__ import annotations

from datetime import datetime
from typing import Any, cast, overload

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    func,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from dojo.model import (
    AuditEvent,
    Client,
    ConsentAcceptance,
    ConsentPolicy,
    Job,
    Package,
    PairingCode,
    Upload,
    YayinIncelemesi,
    YayinZamani,
)


class Base(DeclarativeBase):
    pass


class PackageRow(Base):
    __tablename__ = "packages"
    __table_args__ = (
        Index(
            "ix_packages_status_active",
            "status",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    folder_name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")


class AuditRow(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False)


class PairingCodeRow(Base):
    __tablename__ = "pairing_codes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ClientRow(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    credential_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConsentPolicyRow(Base):
    __tablename__ = "consent_policies"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    version: Mapped[int] = mapped_column(unique=True, nullable=False, index=True)
    text: Mapped[str] = mapped_column(String(4096), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)


class ConsentAcceptanceRow(Base):
    __tablename__ = "consent_acceptances"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    policy_version: Mapped[int] = mapped_column(
        ForeignKey("consent_policies.version"), unique=True, nullable=False, index=True
    )
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepting_client_id: Mapped[int] = mapped_column(nullable=False)
    accepting_client_name: Mapped[str] = mapped_column(String(128), nullable=False)
    accepting_client_kind: Mapped[str] = mapped_column(String(16), nullable=False)


class UploadRow(Base):
    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    upload_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    package_id: Mapped[int] = mapped_column(ForeignKey("packages.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    declared_size_bytes: Mapped[int] = mapped_column(nullable=False)
    received_ranges: Mapped[list] = mapped_column(JSON, nullable=False)
    received_bytes: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    conflict_decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    conflict_target_media_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    upload_id: Mapped[int | None] = mapped_column(ForeignKey("uploads.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    error_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SettingRow(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[object] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class YayinZamaniRow(Base):
    __tablename__ = "yayin_zamani"
    __table_args__ = (Index("ix_yayin_zamani_status_due", "status", "due_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class YayinIncelemesiRow(Base):
    __tablename__ = "yayin_incelemesi"
    __table_args__ = (
        UniqueConstraint(
            "occurrence_id", "revision_digest", name="uq_yayin_incelemesi_occ_rev"
        ),
        Index("ix_yayin_incelemesi_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    occurrence_id: Mapped[int] = mapped_column(nullable=False)
    package_folder: Mapped[str] = mapped_column(Text, nullable=False)
    revision_digest: Mapped[str] = mapped_column(Text, nullable=False)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    oneoff_occurrence_id: Mapped[int | None] = mapped_column(nullable=True)


class PostgresStore:
    def __init__(self, url: str) -> None:
        self._engine = create_engine(url)
        self._session = sessionmaker(bind=self._engine, expire_on_commit=False)

    def create_all(self) -> None:
        Base.metadata.create_all(self._engine)

    def dispose(self) -> None:
        self._engine.dispose()

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
            return self._create_review(obj)
        if isinstance(obj, YayinZamani):
            return self._create_occurrence(obj)
        if isinstance(obj, Upload):
            return self._create_upload(obj)
        if isinstance(obj, Job):
            return self._create_job(obj)
        return self._create_package(obj)

    def _create_package(self, package: Package) -> Package:
        with self._session() as session:
            row = PackageRow(
                folder_name=package.folder_name,
                created_at=package.created_at,
                status=package.status,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return Package(
                id=row.id,
                folder_name=row.folder_name,
                created_at=row.created_at,
                status=row.status,
            )

    def _create_upload(self, upload: Upload) -> Upload:
        with self._session() as session:
            row = UploadRow(
                upload_id=upload.upload_id,
                package_id=upload.package_id,
                filename=upload.filename,
                content_type=upload.content_type,
                declared_size_bytes=upload.declared_size_bytes,
                received_ranges=upload.received_ranges,
                received_bytes=upload.received_bytes,
                status=upload.status,
                error_reason=upload.error_reason,
                conflict_decision=upload.conflict_decision,
                conflict_target_media_id=upload.conflict_target_media_id,
                created_at=upload.created_at,
                updated_at=upload.updated_at,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._upload_from_row(row)

    def _create_job(self, job: Job) -> Job:
        with self._session() as session:
            row = JobRow(
                job_id=job.job_id,
                upload_id=job.upload_id,
                kind=job.kind,
                status=job.status,
                payload=job.payload,
                error_reason=job.error_reason,
                created_at=job.created_at,
                claimed_at=job.claimed_at,
                finished_at=job.finished_at,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._job_from_row(row)

    def get_active(self) -> Package | None:
        with self._session() as session:
            row = session.scalar(
                select(PackageRow)
                .where(PackageRow.status == "active")
                .order_by(PackageRow.id)
                .limit(1)
            )
            if row is None:
                return None
            return self._package_from_row(row)

    def list_completed(self) -> list[Package]:
        with self._session() as session:
            rows = session.scalars(
                select(PackageRow).where(PackageRow.status == "completed").order_by(PackageRow.id)
            ).all()
            return [self._package_from_row(row) for row in rows]

    @staticmethod
    def _package_from_row(row: PackageRow) -> Package:
        return Package(
            id=row.id,
            folder_name=row.folder_name,
            created_at=row.created_at,
            status=row.status,
        )

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
            return self._update_upload(obj)
        if isinstance(obj, Job):
            return self._update_job(obj)
        if isinstance(obj, YayinZamani):
            return self._update_occurrence(obj)
        if isinstance(obj, YayinIncelemesi):
            return self._update_review(obj)
        return self._update_package(obj)

    def _update_review(self, review: YayinIncelemesi) -> YayinIncelemesi:
        with self._session() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(YayinIncelemesiRow)
                    .where(YayinIncelemesiRow.id == review.id)
                    .values(
                        status=review.status,
                        version=review.version,
                        resolved_at=review.resolved_at,
                        resolved_by=review.resolved_by,
                        oneoff_occurrence_id=review.oneoff_occurrence_id,
                    )
                ),
            )
            session.commit()
            if result.rowcount != 1:
                raise ValueError(f"review {review.id} not found")
            row = session.get(YayinIncelemesiRow, review.id)
            assert row is not None
            return self._review_from_row(row)

    def _update_occurrence(self, occ: YayinZamani) -> YayinZamani:
        with self._session() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(YayinZamaniRow)
                    .where(YayinZamaniRow.id == occ.id)
                    .values(
                        kind=occ.kind,
                        due_at=occ.due_at,
                        status=occ.status,
                        resolved_at=occ.resolved_at,
                    )
                ),
            )
            session.commit()
            if result.rowcount != 1:
                raise ValueError(f"occurrence {occ.id} not found")
            row = session.get(YayinZamaniRow, occ.id)
            assert row is not None
            return self._occ_from_row(row)

    def next_regular_after(self, now: datetime) -> YayinZamani | None:
        with self._session() as session:
            row = session.scalar(
                select(YayinZamaniRow)
                .where(
                    YayinZamaniRow.kind == "regular",
                    YayinZamaniRow.status == "pending",
                    YayinZamaniRow.due_at > now,
                )
                .order_by(YayinZamaniRow.due_at)
                .limit(1)
            )
            return self._occ_from_row(row) if row is not None else None

    def _update_package(self, package: Package) -> Package:
        with self._session() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(PackageRow)
                    .where(PackageRow.id == package.id)
                    .values(folder_name=package.folder_name, status=package.status)
                ),
            )
            session.commit()
            if result.rowcount != 1:
                raise ValueError(f"package {package.id} not found")
            row = session.get(PackageRow, package.id)
            assert row is not None
            return self._package_from_row(row)

    def _update_upload(self, upload: Upload) -> Upload:
        with self._session() as session:
            row = session.get(UploadRow, upload.id)
            if row is None:
                raise ValueError(f"upload {upload.id} not found")
            row.upload_id = upload.upload_id
            row.package_id = upload.package_id
            row.filename = upload.filename
            row.content_type = upload.content_type
            row.declared_size_bytes = upload.declared_size_bytes
            row.received_ranges = upload.received_ranges
            row.received_bytes = upload.received_bytes
            row.status = upload.status
            row.error_reason = upload.error_reason
            row.conflict_decision = upload.conflict_decision
            row.conflict_target_media_id = upload.conflict_target_media_id
            row.created_at = upload.created_at
            row.updated_at = upload.updated_at
            session.commit()
            return upload

    def _update_job(self, job: Job) -> Job:
        with self._session() as session:
            row = session.get(JobRow, job.id)
            if row is None:
                raise ValueError(f"job {job.id} not found")
            row.job_id = job.job_id
            row.upload_id = job.upload_id
            row.kind = job.kind
            row.status = job.status
            row.payload = job.payload
            row.error_reason = job.error_reason
            row.created_at = job.created_at
            row.claimed_at = job.claimed_at
            row.finished_at = job.finished_at
            session.commit()
            return job

    def append(self, event: AuditEvent) -> None:
        with self._session() as session:
            session.add(
                AuditRow(
                    action=event.action,
                    actor=event.actor,
                    occurred_at=event.occurred_at,
                    details=event.details,
                )
            )
            session.commit()

    def list_recent(self, limit: int = 50, before_id: int | None = None) -> list[AuditEvent]:
        with self._session() as session:
            stmt = select(AuditRow).order_by(AuditRow.id.desc()).limit(limit)
            if before_id is not None:
                stmt = stmt.where(AuditRow.id < before_id)
            rows = session.scalars(stmt).all()
            return [
                AuditEvent(
                    id=r.id,
                    action=r.action,
                    actor=r.actor,
                    occurred_at=r.occurred_at,
                    details=r.details,
                )
                for r in rows
            ]

    def create_code(self, code: PairingCode) -> PairingCode:
        with self._session() as session:
            row = PairingCodeRow(
                code_hash=code.code_hash,
                expires_at=code.expires_at,
                created_by=code.created_by,
                created_at=code.created_at,
                consumed_at=code.consumed_at,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return PairingCode(
                id=row.id,
                code_hash=row.code_hash,
                expires_at=row.expires_at,
                created_by=row.created_by,
                created_at=row.created_at,
                consumed_at=row.consumed_at,
            )

    def find_code_by_hash(self, code_hash: str) -> PairingCode | None:
        with self._session() as session:
            row = session.scalar(
                select(PairingCodeRow).where(PairingCodeRow.code_hash == code_hash)
            )
            if row is None:
                return None
            return PairingCode(
                id=row.id,
                code_hash=row.code_hash,
                expires_at=row.expires_at,
                created_by=row.created_by,
                created_at=row.created_at,
                consumed_at=row.consumed_at,
            )

    def mark_code_consumed(self, code_id: int, at: datetime) -> bool:
        with self._session() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(PairingCodeRow)
                    .where(
                        PairingCodeRow.id == code_id,
                        PairingCodeRow.consumed_at.is_(None),
                    )
                    .values(consumed_at=at)
                ),
            )
            session.commit()
            return result.rowcount > 0

    def create_client(self, client: Client, credential_hash: str) -> Client:
        with self._session() as session:
            row = ClientRow(
                name=client.name,
                kind=client.kind,
                created_at=client.created_at,
                created_by=client.created_by,
                credential_hash=credential_hash,
                last_seen_at=client.last_seen_at,
                revoked_at=client.revoked_at,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._client_from_row(row)

    def find_client_by_id(self, client_id: int) -> Client | None:
        with self._session() as session:
            row = session.get(ClientRow, client_id)
            return self._client_from_row(row) if row is not None else None

    def find_client_by_credential_hash(self, credential_hash: str) -> Client | None:
        with self._session() as session:
            row = session.scalar(
                select(ClientRow).where(ClientRow.credential_hash == credential_hash)
            )
            return self._client_from_row(row) if row is not None else None

    def list_clients(self) -> list[Client]:
        with self._session() as session:
            rows = session.scalars(select(ClientRow).order_by(ClientRow.id)).all()
            return [self._client_from_row(row) for row in rows]

    def mark_client_revoked(self, client_id: int, at: datetime) -> None:
        with self._session() as session:
            session.execute(
                update(ClientRow)
                .where(ClientRow.id == client_id, ClientRow.revoked_at.is_(None))
                .values(revoked_at=at)
            )
            session.commit()

    def touch_client(self, client_id: int, at: datetime) -> None:
        with self._session() as session:
            session.execute(
                update(ClientRow)
                .where(ClientRow.id == client_id)
                .values(last_seen_at=at)
            )
            session.commit()

    @staticmethod
    def _client_from_row(row: ClientRow) -> Client:
        return Client(
            id=row.id,
            name=row.name,
            kind=row.kind,
            created_at=row.created_at,
            created_by=row.created_by,
            last_seen_at=row.last_seen_at,
            revoked_at=row.revoked_at,
        )

    def create_policy(
        self, *, version: int, text: str, created_by: str, created_at: datetime
    ) -> ConsentPolicy:
        with self._session() as session:
            stmt = pg_insert(ConsentPolicyRow).values(
                version=version, text=text, created_at=created_at, created_by=created_by
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[ConsentPolicyRow.version],
                set_={
                    "text": stmt.excluded.text,
                    "created_at": stmt.excluded.created_at,
                    "created_by": stmt.excluded.created_by,
                },
            )
            session.execute(stmt)
            session.commit()
            row = session.scalar(
                select(ConsentPolicyRow).where(ConsentPolicyRow.version == version)
            )
            assert row is not None
            return self._policy_from_row(row)

    def get_current_policy(self) -> ConsentPolicy | None:
        with self._session() as session:
            row = session.scalar(
                select(ConsentPolicyRow)
                .order_by(ConsentPolicyRow.version.desc())
                .limit(1)
            )
            return self._policy_from_row(row) if row is not None else None

    def get_policy(self, version: int) -> ConsentPolicy | None:
        with self._session() as session:
            row = session.scalar(
                select(ConsentPolicyRow).where(ConsentPolicyRow.version == version)
            )
            return self._policy_from_row(row) if row is not None else None

    def find_acceptance(self, policy_version: int) -> ConsentAcceptance | None:
        with self._session() as session:
            row = session.scalar(
                select(ConsentAcceptanceRow).where(
                    ConsentAcceptanceRow.policy_version == policy_version
                )
            )
            return self._acceptance_from_row(row) if row is not None else None

    def record_acceptance(self, acceptance: ConsentAcceptance) -> bool:
        with self._session() as session:
            try:
                session.add(
                    ConsentAcceptanceRow(
                        policy_version=acceptance.policy_version,
                        accepted_at=acceptance.accepted_at,
                        accepting_client_id=acceptance.accepting_client_id,
                        accepting_client_name=acceptance.accepting_client_name,
                        accepting_client_kind=acceptance.accepting_client_kind,
                    )
                )
                session.commit()
                return True
            except IntegrityError:
                session.rollback()
                return False

    @overload
    def get(self, key: str) -> Upload | None: ...
    @overload
    def get(self, key: str) -> Job | None: ...  # type: ignore[overload-cannot-match]
    @overload
    def get(self, key: str) -> object | None: ...  # type: ignore[overload-cannot-match]
    @overload
    def get(self, key: int) -> YayinIncelemesi | None: ...

    def get(self, key: str | int) -> Upload | Job | object | YayinIncelemesi | None:
        with self._session() as session:
            if isinstance(key, int):
                row = session.get(YayinIncelemesiRow, key)
                return self._review_from_row(row) if row is not None else None
            upload_row = session.scalar(select(UploadRow).where(UploadRow.upload_id == key))
            if upload_row is not None:
                return self._upload_from_row(upload_row)
            job_row = session.scalar(select(JobRow).where(JobRow.job_id == key))
            if job_row is not None:
                return self._job_from_row(job_row)
            setting_row = session.get(SettingRow, key)
            return setting_row.value if setting_row is not None else None

    def get_by_pk(self, upload_pk: int | None) -> Upload | None:
        if upload_pk is None:
            return None
        with self._session() as session:
            row = session.get(UploadRow, upload_pk)
            return self._upload_from_row(row) if row is not None else None

    def list_active(self) -> list[Upload]:
        with self._session() as session:
            rows = session.scalars(
                select(UploadRow).where(UploadRow.status.in_(["receiving", "queued", "processing"]))
            ).all()
            return [self._upload_from_row(r) for r in rows]

    def list_stale(self, cutoff: datetime) -> list[Upload]:
        with self._session() as session:
            rows = session.scalars(
                select(UploadRow).where(
                    UploadRow.status.in_(["receiving", "queued", "conflict"]),
                    UploadRow.updated_at < cutoff,
                )
            ).all()
            return [self._upload_from_row(r) for r in rows]

    def list_conflicts(self, package_id: int) -> list[Upload]:
        with self._session() as session:
            rows = session.scalars(
                select(UploadRow).where(
                    UploadRow.status == "conflict", UploadRow.package_id == package_id
                )
            ).all()
            return [self._upload_from_row(r) for r in rows]

    def get_by_upload(self, upload_pk: int) -> Job | None:
        with self._session() as session:
            row = session.scalar(select(JobRow).where(JobRow.upload_id == upload_pk))
            return self._job_from_row(row) if row is not None else None

    def claim_next(self, claimed_at: datetime) -> Job | None:
        with self._session() as session:
            row = session.scalar(
                select(JobRow)
                .where(JobRow.status == "queued")
                .order_by(JobRow.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if row is None:
                return None
            row.status = "processing"
            row.claimed_at = claimed_at
            session.commit()
            return self._job_from_row(row)

    def set(self, key: str, value: object, *, updated_at: datetime) -> None:
        with self._session() as session:
            stmt = pg_insert(SettingRow).values(key=key, value=value, updated_at=updated_at)
            stmt = stmt.on_conflict_do_update(
                index_elements=[SettingRow.key],
                set_={"value": stmt.excluded.value, "updated_at": stmt.excluded.updated_at},
            )
            session.execute(stmt)
            session.commit()

    def _create_occurrence(self, occ: YayinZamani) -> YayinZamani:
        with self._session() as session:
            row = YayinZamaniRow(
                kind=occ.kind,
                due_at=occ.due_at,
                status=occ.status,
                created_at=occ.created_at,
                resolved_at=occ.resolved_at,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._occ_from_row(row)

    def max_regular_due_at(self) -> datetime | None:
        with self._session() as session:
            return session.scalar(
                select(func.max(YayinZamaniRow.due_at)).where(YayinZamaniRow.kind == "regular")
            )

    def prune_regular_future(self, now: datetime) -> int:
        with self._session() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    delete(YayinZamaniRow).where(
                        YayinZamaniRow.kind == "regular",
                        YayinZamaniRow.due_at > now,
                    )
                ),
            )
            session.commit()
            return result.rowcount or 0

    def has_regular_at(self, due_at: datetime) -> bool:
        with self._session() as session:
            return session.scalar(
                select(YayinZamaniRow.id)
                .where(YayinZamaniRow.kind == "regular", YayinZamaniRow.due_at == due_at)
                .limit(1)
            ) is not None

    def has_pending_manual(self) -> bool:
        with self._session() as session:
            return session.scalar(
                select(YayinZamaniRow.id)
                .where(YayinZamaniRow.kind == "manual", YayinZamaniRow.status == "pending")
                .limit(1)
            ) is not None

    def list_due(self, now: datetime) -> list[YayinZamani]:
        with self._session() as session:
            rows = session.scalars(
                select(YayinZamaniRow)
                .where(YayinZamaniRow.status == "pending", YayinZamaniRow.due_at <= now)
                .order_by(YayinZamaniRow.id)
            ).all()
            return [self._occ_from_row(r) for r in rows]

    def list_all(self) -> list[YayinZamani]:
        with self._session() as session:
            rows = session.scalars(select(YayinZamaniRow).order_by(YayinZamaniRow.id)).all()
            return [self._occ_from_row(r) for r in rows]

    @staticmethod
    def _occ_from_row(row: YayinZamaniRow) -> YayinZamani:
        return YayinZamani(
            id=row.id,
            kind=row.kind,
            due_at=row.due_at,
            status=row.status,
            created_at=row.created_at,
            resolved_at=row.resolved_at,
        )

    def _create_review(self, review: YayinIncelemesi) -> YayinIncelemesi:
        with self._session() as session:
            row = YayinIncelemesiRow(
                occurrence_id=review.occurrence_id,
                package_folder=review.package_folder,
                revision_digest=review.revision_digest,
                caption=review.caption,
                status=review.status,
                created_at=review.created_at,
                version=review.version,
                resolved_at=review.resolved_at,
                resolved_by=review.resolved_by,
                oneoff_occurrence_id=review.oneoff_occurrence_id,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._review_from_row(row)

    def get_by_occurrence_revision(
        self, occurrence_id: int, revision_digest: str
    ) -> YayinIncelemesi | None:
        with self._session() as session:
            row = session.scalar(
                select(YayinIncelemesiRow)
                .where(
                    YayinIncelemesiRow.occurrence_id == occurrence_id,
                    YayinIncelemesiRow.revision_digest == revision_digest,
                )
                .limit(1)
            )
            return self._review_from_row(row) if row is not None else None

    def list_pending(self) -> list[YayinIncelemesi]:
        with self._session() as session:
            rows = session.scalars(
                select(YayinIncelemesiRow)
                .where(YayinIncelemesiRow.status == "pending")
                .order_by(YayinIncelemesiRow.id)
            ).all()
            return [self._review_from_row(r) for r in rows]

    def resolve_if_pending(
        self,
        review_id: int,
        version: int,
        status: str,
        resolved_at: datetime,
        resolved_by: str | None,
    ) -> YayinIncelemesi | None:
        with self._session() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(YayinIncelemesiRow)
                    .where(
                        YayinIncelemesiRow.id == review_id,
                        YayinIncelemesiRow.status == "pending",
                        YayinIncelemesiRow.version == version,
                    )
                    .values(
                        status=status,
                        version=YayinIncelemesiRow.version + 1,
                        resolved_at=resolved_at,
                        resolved_by=resolved_by,
                    )
                ),
            )
            session.commit()
            if result.rowcount != 1:
                return None
            row = session.get(YayinIncelemesiRow, review_id)
            assert row is not None
            return self._review_from_row(row)

    @staticmethod
    def _review_from_row(row: YayinIncelemesiRow) -> YayinIncelemesi:
        return YayinIncelemesi(
            id=row.id,
            occurrence_id=row.occurrence_id,
            package_folder=row.package_folder,
            revision_digest=row.revision_digest,
            caption=row.caption,
            status=row.status,
            created_at=row.created_at,
            version=row.version,
            resolved_at=row.resolved_at,
            resolved_by=row.resolved_by,
            oneoff_occurrence_id=row.oneoff_occurrence_id,
        )

    @staticmethod
    def _upload_from_row(row: UploadRow) -> Upload:
        return Upload(
            id=row.id,
            upload_id=row.upload_id,
            package_id=row.package_id,
            filename=row.filename,
            content_type=row.content_type,
            declared_size_bytes=row.declared_size_bytes,
            received_ranges=row.received_ranges,
            received_bytes=row.received_bytes,
            status=row.status,
            error_reason=row.error_reason,
            conflict_decision=row.conflict_decision,
            conflict_target_media_id=row.conflict_target_media_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _job_from_row(row: JobRow) -> Job:
        return Job(
            id=row.id,
            job_id=row.job_id,
            upload_id=row.upload_id,
            kind=row.kind,
            status=row.status,
            payload=row.payload,
            error_reason=row.error_reason,
            created_at=row.created_at,
            claimed_at=row.claimed_at,
            finished_at=row.finished_at,
        )

    @staticmethod
    def _policy_from_row(row: ConsentPolicyRow) -> ConsentPolicy:
        return ConsentPolicy(
            id=row.id,
            version=row.version,
            text=row.text,
            created_at=row.created_at,
            created_by=row.created_by,
        )

    @staticmethod
    def _acceptance_from_row(row: ConsentAcceptanceRow) -> ConsentAcceptance:
        return ConsentAcceptance(
            id=row.id,
            policy_version=row.policy_version,
            accepted_at=row.accepted_at,
            accepting_client_id=row.accepting_client_id,
            accepting_client_name=row.accepting_client_name,
            accepting_client_kind=row.accepting_client_kind,
        )
