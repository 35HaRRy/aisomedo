from __future__ import annotations

import pytest
from dojo import BrandingConfig, DojoPairing, DojoPublishing, DojoSetup, InMemoryStore
from dojo.testing import FakeClock

from backend.cli import (
    consent_main,
    mint_code,
    set_branding_defaults,
    set_consent_policy,
)


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


def make_publishing(store: InMemoryStore):
    return DojoPublishing(
        packages=store,
        audit=store,
        uploads=store,
        jobs=store,
        settings=store,
        media_root="media",
        clock=FakeClock(),
    )


def test_set_branding_defaults_audits_cli_actor(tmp_path) -> None:
    store = InMemoryStore()
    publishing = make_publishing(store)
    config = set_branding_defaults(
        publishing,
        config=BrandingConfig(logo_asset="logo.png", intro_duration=2.0),
    )
    assert config.logo_asset == "logo.png"
    assert config.intro_duration == 2.0
    events = [e for e in store.list_recent() if e.action == "branding.defaults_updated"]
    assert len(events) == 1
    assert events[0].actor == "cli"


def test_set_caption_template_audits_cli_actor(tmp_path) -> None:
    store = InMemoryStore()
    publishing = make_publishing(store)
    config = set_branding_defaults(
        publishing, config=BrandingConfig(caption_template="Bugün {{isim}}")
    )
    assert config.caption_template == "Bugün {{isim}}"
    events = [e for e in store.list_recent() if e.action == "branding.defaults_updated"]
    assert len(events) == 1
    assert events[0].actor == "cli"
