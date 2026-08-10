from __future__ import annotations

from dojo import DojoPairing, InMemoryStore
from dojo.testing import FakeClock

from backend.cli import mint_code


def test_mint_code_audits_cli_actor() -> None:
    store = InMemoryStore()
    pairing = DojoPairing(pairing=store, audit=store, clock=FakeClock())
    issued = mint_code(pairing)
    assert len(issued.raw_code) == 8
    events = [e for e in store.list_recent() if e.action == "pairing.code_created"]
    assert len(events) == 1
    assert events[0].actor == "cli"
