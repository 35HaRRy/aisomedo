from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from dojo.model import AuditEvent, Client, Package, PairingCode


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
        stored = replace(event, id=self._next_event_id)
        self._next_event_id += 1
        self._events.append(stored)

    def list_recent(self, limit: int = 50, before_id: int | None = None) -> list[AuditEvent]:
        if before_id is not None:
            events = [e for e in reversed(self._events) if e.id < before_id]
        else:
            events = self._events
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
