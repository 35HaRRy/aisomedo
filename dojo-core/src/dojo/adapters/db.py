from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sqlalchemy import JSON, DateTime, String, create_engine, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from dojo.model import AuditEvent, Client, Package, PairingCode


class Base(DeclarativeBase):
    pass


class PackageRow(Base):
    __tablename__ = "packages"

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


class PostgresStore:
    def __init__(self, url: str) -> None:
        self._engine = create_engine(url)
        self._session = sessionmaker(bind=self._engine, expire_on_commit=False)

    def create_all(self) -> None:
        Base.metadata.create_all(self._engine)

    def dispose(self) -> None:
        self._engine.dispose()

    def create(self, package: Package) -> Package:
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
            return Package(
                id=row.id,
                folder_name=row.folder_name,
                created_at=row.created_at,
                status=row.status,
            )

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
