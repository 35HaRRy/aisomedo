from __future__ import annotations

from types import SimpleNamespace

import pytest
from dojo import DojoSetup
from dojo.adapters.memory import InMemoryStore
from dojo.testing import FakeClock

from tests.test_setup import add_client


def configured_setup() -> tuple[DojoSetup, InMemoryStore]:
    store = InMemoryStore()
    clock = FakeClock()
    setup = DojoSetup(
        setup=store,
        audit=store,
        pairing=store,
        clock=clock,
        meta=SimpleNamespace(get_status=lambda: SimpleNamespace(health="healthy")),
    )
    client = add_client(setup, store)
    setup.set_policy(version=1, text="Consent", requester="cli")
    setup.accept_current_policy(client=client)
    for key, value in {
        "branding.logo_asset": "logo.png",
        "branding.caption_template": "Dojo",
        "schedule.anchor_date": "2026-10-05",
        "schedule.anchor_time": "10:00:00",
        "schedule.enabled": False,
    }.items():
        store.set(key, value, updated_at=clock.now())
    return setup, store


def test_checklist_has_all_seven_items_and_optional_cards() -> None:
    setup, store = configured_setup()
    assert [item.key for item in setup.checklist()] == [
        "pairing",
        "instagram",
        "schedule",
        "consent",
        "logo",
        "caption_template",
        "cards",
    ]
    assert setup.checklist_item("cards").required is False
    assert setup.checklist_item("cards").complete is False
    assert setup.is_ready() is True
    unconnected = DojoSetup(setup=store, audit=store, pairing=store)
    assert unconnected.checklist_item("instagram").complete is False
    assert unconnected.is_ready() is False


def test_valid_disabled_monday_plan_is_configured() -> None:
    setup, _ = configured_setup()
    assert setup.checklist_item("schedule").complete is True


@pytest.mark.parametrize(
    "key,value",
    [
        ("schedule.anchor_date", "2026-10-06"),
        ("schedule.anchor_date", "broken"),
        ("schedule.anchor_time", "broken"),
        ("branding.logo_asset", "  "),
        ("branding.caption_template", " \n "),
    ],
)
def test_invalid_required_settings_are_incomplete(key: str, value: str) -> None:
    setup, store = configured_setup()
    store.set(key, value, updated_at=FakeClock().now())
    assert setup.is_ready() is False


def test_skip_cards_persists_without_changing_branding() -> None:
    setup, store = configured_setup()
    setup.skip_cards(requester="1")
    reloaded = DojoSetup(setup=store, audit=store, pairing=store)
    assert reloaded.checklist_item("cards").complete is True
    assert store.get("branding.logo_asset") == "logo.png"
    assert store.get("branding.caption_template") == "Dojo"
    assert any(e.action == "setup.cards_reviewed" for e in store.list_recent())


def test_existing_cards_are_reviewed_when_configured() -> None:
    setup, store = configured_setup()
    store.set("branding.intro_asset", "intro.png", updated_at=FakeClock().now())
    assert setup.checklist_item("cards").complete is True
    store.set("branding.intro_duration", -1, updated_at=FakeClock().now())
    assert setup.checklist_item("cards").complete is False
