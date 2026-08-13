from __future__ import annotations

import pytest
from dojo import DojoPairing, DojoSetup, InMemoryStore
from dojo.testing import FakeClock

from backend.cli import consent_main, mint_code, set_consent_policy


def test_mint_code_audits_cli_actor() -> None:
    store = InMemoryStore()
    pairing = DojoPairing(pairing=store, audit=store, clock=FakeClock())
    issued = mint_code(pairing)
    assert len(issued.raw_code) == 8
    events = [e for e in store.list_recent() if e.action == "pairing.code_created"]
    assert len(events) == 1
    assert events[0].actor == "cli"


def test_set_consent_policy_audits_cli_actor() -> None:
    store = InMemoryStore()
    setup = DojoSetup(setup=store, audit=store, pairing=store, clock=FakeClock())
    policy = set_consent_policy(setup, version=1, text="Riza metni")
    assert policy.version == 1
    events = [e for e in store.list_recent() if e.action == "consent.policy_updated"]
    assert len(events) == 1
    assert events[0].actor == "cli"


def test_consent_main_requires_version_and_text() -> None:
    with pytest.raises(SystemExit) as exc:
        consent_main(["set-policy", "--version", "1"])
    assert exc.value.code == 2
