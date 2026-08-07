from __future__ import annotations

from dataclasses import replace

from dojo.model import AuditEvent, Package


class InMemoryStore:
    def __init__(self) -> None:
        self._packages: list[Package] = []
        self._events: list[AuditEvent] = []
        self._next_id = 1

    def create(self, package: Package) -> Package:
        created = replace(package, id=self._next_id)
        self._next_id += 1
        self._packages.append(created)
        return created

    def get_active(self) -> Package | None:
        for package in reversed(self._packages):
            if package.status == "active":
                return package
        return None

    def append(self, event: AuditEvent) -> None:
        self._events.append(event)

    def list_recent(self, limit: int = 50) -> list[AuditEvent]:
        return self._events[-limit:]
