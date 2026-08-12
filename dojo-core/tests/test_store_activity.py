from __future__ import annotations

from dojo.adapters.memory import InMemoryStore
from dojo.model import AuditEvent
from dojo.testing import FIXED_AT


def append(store: InMemoryStore, i: int) -> None:
    store.append(
        AuditEvent(action="x", actor="system", occurred_at=FIXED_AT, details={"i": i})
    )


def test_memory_assigns_ids_newest_first() -> None:
    store = InMemoryStore()
    append(store, 1)
    append(store, 2)
    assert [(e.id, e.details) for e in store.list_recent()] == [(2, {"i": 2}), (1, {"i": 1})]


def test_memory_before_id_excludes_cursor_and_pages() -> None:
    store = InMemoryStore()
    for i in range(5):
        append(store, i)
    assert [e.id for e in store.list_recent(limit=10, before_id=4)] == [3, 2, 1]
    assert [e.id for e in store.list_recent(limit=2)] == [5, 4]
    assert [e.id for e in store.list_recent(limit=2, before_id=5)] == [4, 3]


def test_memory_limit_respected() -> None:
    store = InMemoryStore()
    for i in range(5):
        append(store, i)
    assert len(store.list_recent(limit=2)) == 2