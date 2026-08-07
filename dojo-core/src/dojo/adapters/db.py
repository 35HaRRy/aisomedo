from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from dojo.model import AuditEvent, Package


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

    def list_recent(self, limit: int = 50) -> list[AuditEvent]:
        with self._session() as session:
            rows = session.scalars(select(AuditRow).order_by(AuditRow.id.desc()).limit(limit)).all()
            return [
                AuditEvent(
                    action=r.action,
                    actor=r.actor,
                    occurred_at=r.occurred_at,
                    details=r.details,
                )
                for r in reversed(rows)
            ]
