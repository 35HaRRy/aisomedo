from __future__ import annotations

from dojo.model import ActivityEntry, ActivityPage, AuditEvent, Client
from dojo.ports import AuditStore, PairingStore

DEFAULT_LIMIT = 50
MAX_LIMIT = 100
LITERAL_ACTORS = frozenset({"system", "cli"})


class DojoActivity:
    """Deep behavioral seam for the audit/activity read path.

    Owns newest-first ordering, exclusive-before-id cursor paging, and
    server-side actor resolution from the free-string actor to the paired
    Client responsible. Domain actions write through both DojoPublishing and
    DojoPairing; this facade is the only read surface.
    """

    def __init__(self, *, audit: AuditStore, pairing: PairingStore) -> None:
        self._audit = audit
        self._pairing = pairing

    def list_activity(
        self, *, limit: int = DEFAULT_LIMIT, before_id: int | None = None
    ) -> ActivityPage:
        limit = max(1, min(MAX_LIMIT, limit))
        events = self._audit.list_recent(limit=limit, before_id=before_id)
        entries = [
            ActivityEntry(
                id=e.id,
                action=e.action,
                occurred_at=e.occurred_at,
                details=e.details,
                actor=self._resolve_actor(e),
            )
            for e in events
        ]
        next_cursor = entries[-1].id if len(entries) == limit else None
        return ActivityPage(entries=entries, next_cursor=next_cursor)

    def _resolve_actor(self, event: AuditEvent) -> Client | str:
        actor = event.actor
        if actor in LITERAL_ACTORS:
            return actor
        try:
            client_id = int(actor)
        except ValueError:
            return actor
        client = self._pairing.find_client_by_id(client_id)
        return client if client is not None else actor