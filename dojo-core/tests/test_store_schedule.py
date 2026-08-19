from __future__ import annotations

from datetime import datetime, timedelta

from dojo import InMemoryStore, YayinZamani
from dojo.testing import FIXED_AT


def make_occ(
    store: InMemoryStore, *, kind: str, due: datetime, status: str = "pending"
) -> YayinZamani:
    return store.create(
        YayinZamani(
            id=0,
            kind=kind,
            due_at=due,
            status=status,
            created_at=FIXED_AT,
        )
    )


def test_create_assigns_id_and_stores() -> None:
    store = InMemoryStore()
    occ = make_occ(store, kind="manual", due=FIXED_AT)
    assert occ.id >= 1
    assert len(store.list_all()) == 1
    assert store.list_all()[0].kind == "manual"


def test_max_regular_due_at() -> None:
    store = InMemoryStore()
    make_occ(store, kind="regular", due=FIXED_AT)
    make_occ(store, kind="regular", due=FIXED_AT + timedelta(days=14))
    make_occ(store, kind="manual", due=FIXED_AT + timedelta(days=99))
    assert store.max_regular_due_at() == FIXED_AT + timedelta(days=14)


def test_max_regular_due_at_empty() -> None:
    assert InMemoryStore().max_regular_due_at() is None


def test_has_regular_at() -> None:
    store = InMemoryStore()
    make_occ(store, kind="regular", due=FIXED_AT)
    assert store.has_regular_at(FIXED_AT) is True
    assert store.has_regular_at(FIXED_AT + timedelta(days=14)) is False


def test_has_pending_manual() -> None:
    store = InMemoryStore()
    assert store.has_pending_manual() is False
    make_occ(store, kind="manual", due=FIXED_AT)
    assert store.has_pending_manual() is True


def test_list_due() -> None:
    store = InMemoryStore()
    past = make_occ(store, kind="regular", due=FIXED_AT - timedelta(days=1))
    future = make_occ(store, kind="regular", due=FIXED_AT + timedelta(days=14))
    assert [o.id for o in store.list_due(FIXED_AT)] == [past.id]
    assert all(o.id != future.id for o in store.list_due(FIXED_AT))
