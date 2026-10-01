from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from typing import Any, cast, overload
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    func,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

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
    ALERT_KIND_CHECK,
    DELIVERY_ATTEMPTS_CHECK,
    DELIVERY_COMPLETE,
    DELIVERY_PENDING,
    DELIVERY_SKIPPED,
    DELIVERY_STATUS_CHECK,
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
    __table_args__ = (
        Index(
            "uq_jobs_active_render", text("(payload ->> 'package')"),
            text("(payload ->> 'digest')"), unique=True,
            postgresql_where=text("kind = 'render' AND status IN ('queued', 'processing')"),
        ),
    )

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
    failure_generation: Mapped[int] = mapped_column(
        nullable=False, default=0, server_default=text("0"),
    )


class MonitoringIncidentRow(Base):
    """One row per monitored target: the active incident and the last sample."""

    __tablename__ = "monitoring_incidents"

    target: Mapped[str] = mapped_column(String(64), primary_key=True)
    active_incident_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_sampled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class OperationalAlertRow(Base):
    __tablename__ = "operational_alerts"
    __table_args__ = (CheckConstraint(ALERT_KIND_CHECK, name="ck_operational_alerts_kind"),)

    alert_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    body: Mapped[str] = mapped_column(String(512), nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recipients_snapshotted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class OperationalDeliveryRow(Base):
    """One recipient's attempts for one alert; no plaintext token is stored."""

    __tablename__ = "operational_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "alert_id", "client_id", name="uq_operational_deliveries_alert_client",
        ),
        CheckConstraint(DELIVERY_STATUS_CHECK, name="ck_operational_deliveries_status"),
        CheckConstraint(DELIVERY_ATTEMPTS_CHECK, name="ck_operational_deliveries_attempts"),
        Index("ix_operational_deliveries_due", "status", "due_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    alert_id: Mapped[str] = mapped_column(
        ForeignKey("operational_alerts.alert_id"), nullable=False
    )
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    token_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claim_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SettingRow(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[object] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class YayinZamaniRow(Base):
    __tablename__ = "yayin_zamani"
    __table_args__ = (
        Index("ix_yayin_zamani_status_due", "status", "due_at"),
        Index("uq_yayin_zamani_regular_due", "due_at", unique=True,
              postgresql_where=text("kind = 'regular'")),
    )

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
    last_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PushRegistrationRow(Base):
    __tablename__ = "push_registrations"

    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), primary_key=True)
    token: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MetaConnectionRow(Base):
    __tablename__ = "meta_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    ig_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    ig_username: Mapped[str] = mapped_column(Text, nullable=False)
    page_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    connection_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="facebook_login", server_default="facebook_login"
    )
    health: Mapped[str] = mapped_column(String(32), nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class MetaOAuthAttemptRow(Base):
    __tablename__ = "meta_oauth_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    initiated_by_client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False)
    return_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    candidates: Mapped[list | None] = mapped_column(JSON, nullable=True)
    encrypted_temp_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    temp_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class PostgresStore:
    def __init__(self, url: str) -> None:
        self._engine = create_engine(url)
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)
        self._emission_connection: ContextVar[Connection | None] = ContextVar(
            "emission_connection", default=None,
        )

    def _session(self) -> Session:
        connection = self._emission_connection.get()
        if connection is None:
            return self._session_factory()
        # Method-local sessions flush on commit, but neither commit nor close
        # the outer transaction. Reads/refreshes also use the lock connection.
        return self._session_factory(bind=connection, join_transaction_mode="rollback_only")

    @contextmanager
    def emission_transaction(self) -> Iterator[None]:
        """Own one turn's commit/rollback; nesting on this store is an error.

        Context-local connection state isolates concurrent worker threads.
        Always reset it, including on disconnect, before a later turn can run.
        """
        if self._emission_connection.get() is not None:
            raise RuntimeError("nested emission transactions are not supported")
        with self._engine.begin() as connection:
            token = self._emission_connection.set(connection)
            try:
                yield
            finally:
                self._emission_connection.reset(token)

    def try_advisory_xact_lock(self, key: int) -> bool:
        connection = self._emission_connection.get()
        if connection is None:
            raise RuntimeError("advisory lock requires an emission transaction")
        return bool(connection.execute(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key},
        ).scalar_one())

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
        # Legacy single-insert path: duplicates raise (IntegrityError). Race-safe
        # callers must use create_job_once instead.
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

    def create_job_once(
        self, job: Job, *, audit: AuditEvent | None = None,
    ) -> tuple[Job, bool]:
        """Return (durable job, created); only new rows get the atomic audit.

        Active render identity is package/digest. Terminal history is never reused.
        Conflict-aware insertion preserves any enclosing emission transaction.
        """
        values = asdict(job)
        values.pop("id")
        stmt = pg_insert(JobRow).values(**values)
        active_render = job.kind == "render" and job.status in ("queued", "processing")
        if active_render:
            stmt = stmt.on_conflict_do_nothing(
                index_elements=[text("(payload ->> 'package')"), text("(payload ->> 'digest')")],
                index_where=text("kind = 'render' AND status IN ('queued', 'processing')"),
            )
        with self._session() as session:
            while True:
                row = session.scalar(stmt.returning(JobRow))
                created = row is not None
                if row is None:
                    # A separate statement gets a fresh READ COMMITTED snapshot.
                    # Lock the winner against completion until our transaction ends.
                    row = session.scalar(select(JobRow).where(
                        JobRow.kind == "render",
                        JobRow.status.in_(("queued", "processing")),
                        JobRow.payload["package"].as_string() == job.payload["package"],
                        JobRow.payload["digest"].as_string() == job.payload["digest"],
                    ).with_for_update())
                if row is not None:
                    if created and audit is not None:
                        self._add_audit(session, audit)
                    session.commit()
                    return self._job_from_row(row), created
                # Winner completed/deleted between INSERT and SELECT: try anew.

    @staticmethod
    def _add_audit(session: Session, event: AuditEvent) -> None:
        values = asdict(event)
        values.pop("id")
        session.add(AuditRow(**values))

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

    def get_publishing(self) -> Package | None:
        with self._session() as session:
            row = session.scalar(
                select(PackageRow)
                .where(PackageRow.status == "publishing")
                .order_by(PackageRow.id)
                .limit(1)
            )
            if row is None:
                return None
            return self._package_from_row(row)

    def get_by_folder(self, folder_name: str) -> Package | None:
        with self._session() as session:
            row = session.scalar(
                select(PackageRow).where(PackageRow.folder_name == folder_name).limit(1)
            )
            if row is None:
                return None
            return self._package_from_row(row)

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
                        last_reminded_at=review.last_reminded_at,
                    )
                ),
            )
            session.commit()
            if result.rowcount != 1:
                raise ValueError(f"review {review.id} not found")
            row = session.get(YayinIncelemesiRow, review.id)
            assert row is not None
            return self._review_from_row(row)

    def update_last_reminded_at(self, review_id: int, at: datetime) -> YayinIncelemesi | None:
        with self._session() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(YayinIncelemesiRow)
                    .where(YayinIncelemesiRow.id == review_id)
                    .values(last_reminded_at=at)
                ),
            )
            session.commit()
            if result.rowcount != 1:
                return None
            row = session.get(YayinIncelemesiRow, review_id)
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
            # The lock makes "nonfailed -> failed" a one-writer transition, so the
            # generation and its alert cannot race or be emitted twice.
            row = session.get(JobRow, job.id, with_for_update=True)
            if row is None:
                raise ValueError(f"job {job.id} not found")
            newly_failed = row.status != "failed" and job.status == "failed"
            row.job_id = job.job_id
            row.upload_id = job.upload_id
            row.kind = job.kind
            row.status = job.status
            row.payload = job.payload
            row.error_reason = job.error_reason
            row.created_at = job.created_at
            row.claimed_at = job.claimed_at
            row.finished_at = job.finished_at
            if newly_failed:
                row.failure_generation = row.failure_generation + 1
                self._add_alert(session, job_failure_alert(
                    alert_id=str(uuid4()),
                    event_key=job_failure_event_key(row.job_id, row.failure_generation),
                    job_id=row.job_id,
                    kind=row.kind,
                    created_at=row.finished_at or row.created_at,
                ))
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
            session.execute(select(func.pg_advisory_xact_lock(func.hashtext("dojo.consent-policy"))))
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

    def accept_policy_version(
        self, *, client: Client, version: int | None, accepted_at: datetime
    ) -> tuple[ConsentAcceptance, bool]:
        with self._session() as session:
            session.execute(text("SELECT pg_advisory_xact_lock(hashtext('dojo.consent-policy'))"))
            policy = session.scalar(
                select(ConsentPolicyRow).order_by(ConsentPolicyRow.version.desc()).limit(1)
            )
            if policy is None:
                raise NoConsentPolicy("no consent policy configured")
            if version is not None and version != policy.version:
                raise ConsentPolicyChanged("consent policy changed; reload before accepting")
            row = session.scalar(select(ConsentAcceptanceRow).where(
                ConsentAcceptanceRow.policy_version == policy.version
            ))
            if row is not None:
                return self._acceptance_from_row(row), False
            row = ConsentAcceptanceRow(
                policy_version=policy.version, accepted_at=accepted_at,
                accepting_client_id=client.id, accepting_client_name=client.name,
                accepting_client_kind=client.kind,
            )
            session.add(row)
            session.flush()
            acceptance = self._acceptance_from_row(row)
            session.commit()
            return acceptance, True

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
        # Regular due-time identity: repeated creation returns the existing row
        # (conflict-aware, preserves the enclosing emission transaction); one-off
        # occurrences always insert. Legacy callers relied on has_regular_at guards.
        values = asdict(occ)
        values.pop("id")
        stmt = pg_insert(YayinZamaniRow).values(**values)
        if occ.kind == "regular":
            stmt = stmt.on_conflict_do_nothing(
                index_elements=[YayinZamaniRow.due_at], index_where=text("kind = 'regular'"),
            )
        with self._session() as session:
            while True:
                row = session.scalar(stmt.returning(YayinZamaniRow))
                if row is None:
                    row = session.scalar(select(YayinZamaniRow).where(
                        YayinZamaniRow.kind == "regular", YayinZamaniRow.due_at == occ.due_at,
                    ).with_for_update())
                if row is not None:
                    session.commit()
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
        # Legacy single-insert path: duplicates raise (IntegrityError). Race-safe
        # callers must use create_review_once instead.
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
                last_reminded_at=review.last_reminded_at,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._review_from_row(row)

    def create_review_once(
        self, review: YayinIncelemesi, *, audit: AuditEvent | None = None,
    ) -> tuple[YayinIncelemesi, bool]:
        """Insert once per occurrence/revision; add review_id to a new row's audit."""
        values = asdict(review)
        values.pop("id")
        stmt = pg_insert(YayinIncelemesiRow).values(**values).on_conflict_do_nothing(
            constraint="uq_yayin_incelemesi_occ_rev",
        )
        with self._session() as session:
            while True:
                row = session.scalar(stmt.returning(YayinIncelemesiRow))
                created = row is not None
                if row is None:
                    row = session.scalar(select(YayinIncelemesiRow).where(
                        YayinIncelemesiRow.occurrence_id == review.occurrence_id,
                        YayinIncelemesiRow.revision_digest == review.revision_digest,
                    ).with_for_update())
                if row is not None:
                    if created and audit is not None:
                        self._add_audit(session, replace(
                            audit, details={**audit.details, "review_id": row.id},
                        ))
                    session.commit()
                    return self._review_from_row(row), created

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
            last_reminded_at=row.last_reminded_at,
        )

    def register_token(self, client_id: int, token: str, at: datetime) -> PushRegistration:
        with self._session() as session:
            # remove previous owner of this token
            session.execute(delete(PushRegistrationRow).where(PushRegistrationRow.token == token))
            # upsert for client_id
            existing = session.get(PushRegistrationRow, client_id)
            if existing is not None:
                existing.token = token
                existing.updated_at = at
            else:
                session.add(PushRegistrationRow(client_id=client_id, token=token, updated_at=at))
            session.commit()
            row = session.get(PushRegistrationRow, client_id)
            assert row is not None
            return PushRegistration(
                client_id=row.client_id, token=row.token, updated_at=row.updated_at
            )

    def remove_by_client(self, client_id: int) -> None:
        with self._session() as session:
            session.execute(delete(PushRegistrationRow).where(PushRegistrationRow.client_id == client_id))
            session.commit()

    def remove_by_token(self, token: str) -> None:
        with self._session() as session:
            session.execute(delete(PushRegistrationRow).where(PushRegistrationRow.token == token))
            session.commit()

    def list_active_device_tokens(self) -> list[PushRegistration]:
        with self._session() as session:
            return self._active_device_registrations(session)

    @staticmethod
    def _active_device_registrations(session: Session) -> list[PushRegistration]:
        """Active paired Android registrations, read inside the caller's transaction."""
        rows = session.scalars(
            select(PushRegistrationRow)
            .join(ClientRow, ClientRow.id == PushRegistrationRow.client_id)
            .where(ClientRow.revoked_at.is_(None), ClientRow.kind == "device")
            .order_by(PushRegistrationRow.client_id)
        ).all()
        return [
            PushRegistration(client_id=r.client_id, token=r.token, updated_at=r.updated_at)
            for r in rows
        ]

    # Operational monitoring
    @staticmethod
    def _add_alert(session: Session, alert: OperationalAlert) -> None:
        # Event keys are unique, so a replayed insert is dropped rather than
        # failing the job transition that produced it.
        session.execute(
            pg_insert(OperationalAlertRow).values(
                alert_id=alert.alert_id,
                event_key=alert.event_key,
                kind=alert.kind,
                title=alert.title,
                body=alert.body,
                data=alert.data,
                created_at=alert.created_at,
                recipients_snapshotted_at=None,
            ).on_conflict_do_nothing(index_elements=[OperationalAlertRow.event_key])
        )

    def record_disk_sample(
        self, sample: DiskSample, *, low_percent: float, recovery_percent: float,
    ) -> None:
        free_percent = sample.free_percent
        with self._session() as session:
            session.execute(
                pg_insert(MonitoringIncidentRow)
                .values(target=sample.target, active_incident_id=None, last_sampled_at=None)
                .on_conflict_do_nothing(index_elements=[MonitoringIncidentRow.target])
            )
            # The target row lock serializes concurrent samplers of one target.
            row = session.get(MonitoringIncidentRow, sample.target, with_for_update=True)
            assert row is not None
            if row.last_sampled_at is not None and sample.sampled_at <= row.last_sampled_at:
                return  # Stale or repeated reading: cannot open or close anything.
            row.last_sampled_at = sample.sampled_at
            if row.active_incident_id is None:
                if free_percent < low_percent:
                    incident_id = str(uuid4())
                    row.active_incident_id = incident_id
                    self._add_alert(session, disk_low_alert(
                        alert_id=str(uuid4()),
                        event_key=disk_event_key(sample.target, incident_id, DISK_OPENED),
                        target=sample.target,
                        created_at=sample.sampled_at,
                    ))
            elif free_percent >= recovery_percent:
                incident_id = row.active_incident_id
                row.active_incident_id = None
                self._add_alert(session, disk_recovered_alert(
                    alert_id=str(uuid4()),
                    event_key=disk_event_key(sample.target, incident_id, DISK_RECOVERED),
                    target=sample.target,
                    created_at=sample.sampled_at,
                ))
            session.commit()

    def prepare_alert_deliveries(self, now: datetime, *, limit: int = 100) -> int:
        prepared = 0
        with self._session() as session:
            recipients = self._active_device_registrations(session)
            if not recipients:
                return 0  # No recipient is not a delivery: alerts stay pending.
            # Locking the alerts makes the snapshot single-writer: a concurrent
            # preparer skips them instead of racing the unique recipient rows.
            unsnapshotted = session.scalars(
                select(OperationalAlertRow)
                .where(OperationalAlertRow.recipients_snapshotted_at.is_(None))
                .order_by(OperationalAlertRow.created_at, OperationalAlertRow.alert_id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            for alert in unsnapshotted:
                # One snapshot for the whole batch: devices paired after this
                # point are not historical recipients of these alerts.
                for registration in recipients:
                    session.add(OperationalDeliveryRow(
                        alert_id=alert.alert_id,
                        client_id=registration.client_id,
                        status=DELIVERY_PENDING,
                        attempts=0,
                        due_at=now,
                    ))
                alert.recipients_snapshotted_at = now
                prepared += 1
            session.commit()
        return prepared

    def claim_alert_delivery(
        self, now: datetime, *, lease_seconds: int = 60,
    ) -> DeliveryLease | None:
        with self._session() as session:
            while True:
                row = session.scalar(
                    select(OperationalDeliveryRow)
                    .where(
                        OperationalDeliveryRow.status == DELIVERY_PENDING,
                        OperationalDeliveryRow.due_at <= now,
                        or_(
                            OperationalDeliveryRow.claim_id.is_(None),
                            OperationalDeliveryRow.lease_expires_at <= now,
                        ),
                    )
                    .order_by(OperationalDeliveryRow.due_at, OperationalDeliveryRow.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                if row is None:
                    return None
                registration = self._current_registration(session, row.client_id)
                if registration is None:
                    # Revoked, de-paired or non-device recipients are terminal:
                    # resending to them can only fail forever.
                    row.status = DELIVERY_SKIPPED
                    row.claim_id = None
                    row.lease_expires_at = None
                    session.commit()
                    continue
                claim_id = str(uuid4())
                row.claim_id = claim_id
                row.attempts = row.attempts + 1
                row.token_fingerprint = token_fingerprint(registration.token)
                row.lease_expires_at = now + timedelta(seconds=lease_seconds)
                alert_row = session.get(OperationalAlertRow, row.alert_id)
                assert alert_row is not None
                lease = DeliveryLease(
                    delivery_id=row.id,
                    claim_id=claim_id,
                    alert=self._alert_from_row(alert_row),
                    client_id=row.client_id,
                    token=registration.token,
                    attempt=row.attempts,
                )
                session.commit()
                return lease

    @staticmethod
    def _current_registration(
        session: Session, client_id: int,
    ) -> PushRegistration | None:
        """The registration a claim may use, rechecked for revocation."""
        row = session.get(PushRegistrationRow, client_id)
        if row is None:
            return None
        client = session.get(ClientRow, client_id)
        if client is None or client.revoked_at is not None or client.kind != "device":
            return None
        return PushRegistration(
            client_id=row.client_id, token=row.token, updated_at=row.updated_at
        )

    def finish_alert_delivery(
        self, lease: DeliveryLease, *, outcome: DeliveryOutcome, now: datetime,
    ) -> bool:
        with self._session() as session:
            row = session.get(OperationalDeliveryRow, lease.delivery_id, with_for_update=True)
            if (
                row is None
                or row.status != DELIVERY_PENDING
                or row.claim_id != lease.claim_id
                or row.lease_expires_at is None
                or row.lease_expires_at <= now
            ):
                return False
            row.claim_id = None
            row.lease_expires_at = None
            if outcome == "accepted":
                row.status = DELIVERY_COMPLETE
            else:
                row.status = DELIVERY_PENDING
                row.due_at = now + timedelta(seconds=retry_delay_seconds(row.attempts))
                if outcome == "invalid":
                    # Delete exactly the token that was used: a registration that
                    # has since rotated must survive and stay deliverable.
                    session.execute(
                        delete(PushRegistrationRow).where(
                            PushRegistrationRow.token == lease.token,
                            PushRegistrationRow.client_id == lease.client_id,
                        )
                    )
            session.commit()
            return True

    @staticmethod
    def _alert_from_row(row: OperationalAlertRow) -> OperationalAlert:
        return OperationalAlert(
            alert_id=row.alert_id,
            event_key=row.event_key,
            kind=row.kind,
            title=row.title,
            body=row.body,
            data=row.data,
            created_at=row.created_at,
        )

    # Meta connection store
    def get_meta_status(self) -> MetaConnectionStatus | None:
        snapshot = self.get_active_snapshot()
        return snapshot[0] if snapshot else None

    def get_active_snapshot(self) -> tuple[MetaConnectionStatus, str] | None:
        with self._session() as session:
            row = session.get(MetaConnectionRow, 1)
            if row is None:
                return None
            status = MetaConnectionStatus(
                health=row.health,
                ig_user_id=row.ig_user_id,
                ig_username=row.ig_username,
                page_id=row.page_id,
                page_name=row.page_name,
                expires_at=row.token_expires_at,
                last_checked_at=row.last_checked_at,
                last_refreshed_at=row.last_refreshed_at,
                last_error=row.last_error,
                connection_type=row.connection_type,
            )
            return status, row.encrypted_token

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
        with self._session() as session:
            row = session.get(MetaConnectionRow, 1)
            if row is None:
                row = MetaConnectionRow(
                    id=1,
                    ig_user_id=ig_user_id,
                    ig_username=ig_username,
                    page_id=page_id,
                    page_name=page_name,
                    encrypted_token=encrypted_token,
                    token_expires_at=token_expires_at,
                    health=health,
                    last_checked_at=last_checked_at,
                    last_refreshed_at=last_refreshed_at,
                    last_error=last_error,
                    connection_type=connection_type,
                )
                session.add(row)
            else:
                row.ig_user_id = ig_user_id
                row.ig_username = ig_username
                row.page_id = page_id
                row.page_name = page_name
                row.encrypted_token = encrypted_token
                row.token_expires_at = token_expires_at
                row.health = health
                row.last_checked_at = last_checked_at
                row.last_refreshed_at = last_refreshed_at
                row.last_error = last_error
                row.connection_type = connection_type
            session.commit()
            return MetaConnectionStatus(
                health=row.health,
                ig_user_id=row.ig_user_id,
                ig_username=row.ig_username,
                page_id=row.page_id,
                page_name=row.page_name,
                expires_at=row.token_expires_at,
                last_checked_at=row.last_checked_at,
                last_refreshed_at=row.last_refreshed_at,
                last_error=row.last_error,
                connection_type=row.connection_type,
            )

    def get_raw_active(self) -> tuple[str, datetime | None] | None:
        with self._session() as session:
            row = session.get(MetaConnectionRow, 1)
            if row is None:
                return None
            return row.encrypted_token, row.token_expires_at

    def update_health(
        self, health: str, last_checked_at: datetime | None, last_error: str | None,
        *, expected_encrypted_token: str | None = None,
    ) -> MetaConnectionStatus | None:
        with self._session() as session:
            row = session.get(MetaConnectionRow, 1, with_for_update=True)
            if row is None:
                return None
            if (
                expected_encrypted_token is not None
                and row.encrypted_token != expected_encrypted_token
            ):
                return None
            row.health = health
            row.last_checked_at = last_checked_at
            row.last_error = last_error
            session.commit()
            return MetaConnectionStatus(
                health=row.health,
                ig_user_id=row.ig_user_id,
                ig_username=row.ig_username,
                page_id=row.page_id,
                page_name=row.page_name,
                expires_at=row.token_expires_at,
                last_checked_at=row.last_checked_at,
                last_refreshed_at=row.last_refreshed_at,
                last_error=row.last_error,
                connection_type=row.connection_type,
            )

    def update_token(
        self, encrypted_token: str, token_expires_at: datetime, last_refreshed_at: datetime,
        *, expected_encrypted_token: str | None = None,
    ) -> MetaConnectionStatus | None:
        with self._session() as session:
            row = session.get(MetaConnectionRow, 1, with_for_update=True)
            if row is None:
                return None
            if (
                expected_encrypted_token is not None
                and row.encrypted_token != expected_encrypted_token
            ):
                return None
            row.encrypted_token = encrypted_token
            row.token_expires_at = token_expires_at
            row.last_refreshed_at = last_refreshed_at
            session.commit()
            return MetaConnectionStatus(
                health=row.health,
                ig_user_id=row.ig_user_id,
                ig_username=row.ig_username,
                page_id=row.page_id,
                page_name=row.page_name,
                expires_at=row.token_expires_at,
                last_checked_at=row.last_checked_at,
                last_refreshed_at=row.last_refreshed_at,
                last_error=row.last_error,
                connection_type=row.connection_type,
            )

    def get_meta_attempt(self, attempt_id: str) -> dict | None:
        with self._session() as session:
            row = session.get(MetaOAuthAttemptRow, attempt_id)
            if row is None:
                return None
            return {
                "id": row.id,
                "state_hash": row.state_hash,
                "initiated_by_client_id": row.initiated_by_client_id,
                "return_uri": row.return_uri,
                "status": row.status,
                "created_at": row.created_at,
                "expires_at": row.expires_at,
                "candidates": row.candidates,
                "encrypted_temp_token": row.encrypted_temp_token,
                "temp_token_expires_at": row.temp_token_expires_at,
                "last_error": row.last_error,
            }

    def find_attempt_by_state_hash(self, state_hash: str) -> dict | None:
        with self._session() as session:
            row = session.scalar(select(MetaOAuthAttemptRow).where(MetaOAuthAttemptRow.state_hash == state_hash))
            if row is None:
                return None
            return {
                "id": row.id,
                "state_hash": row.state_hash,
                "initiated_by_client_id": row.initiated_by_client_id,
                "return_uri": row.return_uri,
                "status": row.status,
                "created_at": row.created_at,
                "expires_at": row.expires_at,
                "candidates": row.candidates,
                "encrypted_temp_token": row.encrypted_temp_token,
                "temp_token_expires_at": row.temp_token_expires_at,
                "last_error": row.last_error,
            }

    def create_attempt(self, attempt: dict) -> dict:
        with self._session() as session:
            row = MetaOAuthAttemptRow(
                id=attempt["id"],
                state_hash=attempt["state_hash"],
                initiated_by_client_id=attempt["initiated_by_client_id"],
                return_uri=attempt.get("return_uri"),
                status=attempt["status"],
                created_at=attempt["created_at"],
                expires_at=attempt["expires_at"],
                candidates=attempt.get("candidates"),
                encrypted_temp_token=attempt.get("encrypted_temp_token"),
                temp_token_expires_at=attempt.get("temp_token_expires_at"),
                last_error=attempt.get("last_error"),
            )
            session.add(row)
            session.commit()
            return attempt

    def mark_attempt_completed(
        self,
        attempt_id: str,
        candidates: list[MetaCandidate],
        encrypted_temp_token: str | None,
        temp_token_expires_at: datetime | None,
    ) -> None:
        with self._session() as session:
            row = session.get(MetaOAuthAttemptRow, attempt_id)
            if row is None:
                return
            row.status = "completed"
            row.candidates = [c.to_dict() for c in candidates]
            row.encrypted_temp_token = encrypted_temp_token
            row.temp_token_expires_at = temp_token_expires_at
            session.commit()

    def mark_attempt_failed(self, attempt_id: str, error: str) -> None:
        with self._session() as session:
            row = session.get(MetaOAuthAttemptRow, attempt_id)
            if row is None:
                return
            row.status = "failed"
            row.last_error = error
            session.commit()

    def consume_attempt(self, attempt_id: str) -> dict | None:
        with self._session() as session:
            row = session.get(MetaOAuthAttemptRow, attempt_id)
            if row is None:
                return None
            data = {
                "id": row.id,
                "state_hash": row.state_hash,
                "initiated_by_client_id": row.initiated_by_client_id,
                "return_uri": row.return_uri,
                "status": row.status,
                "created_at": row.created_at,
                "expires_at": row.expires_at,
                "candidates": row.candidates,
                "encrypted_temp_token": row.encrypted_temp_token,
                "temp_token_expires_at": row.temp_token_expires_at,
                "last_error": row.last_error,
            }
            session.delete(row)
            session.commit()
            return data

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
