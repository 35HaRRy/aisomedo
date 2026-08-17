from __future__ import annotations

import json

import pytest
from dojo import (
    ActivePackageExists,
    BrandingConfig,
    DojoPublishing,
    InMemoryStore,
    LogoNotConfigured,
    NoActivePackage,
)
from dojo.adapters.stubs import StubMetaPublisher, StubNotifier, StubSignedUrlStore
from dojo.testing import FIXED_AT, FakeClock


def make_seam(tmp_path, **overrides):
    store = InMemoryStore()
    return (
        store,
        DojoPublishing(
            packages=store,
            audit=store,
            media_root=tmp_path,
            clock=FakeClock(),
            meta=StubMetaPublisher(),
            notifier=StubNotifier(),
            signed_urls=StubSignedUrlStore(),
            **overrides,
        ),
    )


def test_ensure_active_package_creates_folder_manifest_row_and_audit(tmp_path):
    store, seam = make_seam(tmp_path)

    package = seam.ensure_active_package()

    assert package.folder_name == "06-08-2026 14-30"
    assert package.status == "active"

    folder = tmp_path / "06-08-2026 14-30"
    assert folder.is_dir()
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest == {
        "media": [],
        "order": [],
        "trims": {},
        "caption": None,
        "branding": {
            "logo_asset": None,
            "intro_asset": None,
            "intro_duration": None,
            "outro_asset": None,
            "outro_duration": None,
        },
        "render_revision": None,
        "meta": {},
        "recovery": {},
    }

    assert store.get_active() == package
    events = seam.list_audit()
    assert len(events) == 1
    assert events[0].action == "package.created"
    assert events[0].details == {"folder_name": "06-08-2026 14-30"}
    assert events[0].occurred_at == FIXED_AT


def test_ensure_active_package_second_call_raises(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()

    with pytest.raises(ActivePackageExists):
        seam.ensure_active_package()

    assert len(list(tmp_path.iterdir())) == 1


def test_get_active_package_returns_none_when_absent(tmp_path):
    _, seam = make_seam(tmp_path)
    assert seam.get_active_package() is None


def test_evaluate_due_work_is_a_noop(tmp_path):
    _, seam = make_seam(tmp_path)
    assert seam.evaluate_due_work() is None


def test_ensure_active_package_attributed_to_requester(tmp_path):
    store, seam = make_seam(tmp_path)

    package = seam.ensure_active_package(requester="7")

    assert package.status == "active"
    events = seam.list_audit()
    assert events[0].actor == "7"


def test_stubbed_methods_raise_not_implemented(tmp_path):
    _, seam = make_seam(tmp_path)
    for method in ("add_media", "approve"):
        with pytest.raises(NotImplementedError):
            getattr(seam, method)()
    with pytest.raises(LogoNotConfigured):
        seam.publish()


def test_publish_with_logo_config_falls_through_to_stub(tmp_path):
    store, seam = make_seam(tmp_path)
    store.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    with pytest.raises(NotImplementedError):
        seam.publish()


def test_publish_honors_draft_logo_override_when_global_unset(tmp_path):
    store, seam = make_seam(tmp_path)
    seam.set_branding_defaults(BrandingConfig(), requester="setup")
    seam.ensure_active_package(requester="1")
    seam.set_branding({"logo_asset": "draft-logo.png"}, requester="1")
    with pytest.raises(NotImplementedError):
        seam.publish()


def test_publish_falls_back_to_global_logo_when_draft_logo_unset(tmp_path):
    store, seam = make_seam(tmp_path)
    store.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    seam.ensure_active_package(requester="1")
    with pytest.raises(NotImplementedError):
        seam.publish()


def test_get_or_create_returns_existing_active_package(tmp_path):
    _, seam = make_seam(tmp_path)
    first = seam.ensure_active_package()
    second = seam.get_or_create_active_package()
    assert second == first


def test_get_or_create_creates_when_absent(tmp_path):
    store, seam = make_seam(tmp_path)
    package = seam.get_or_create_active_package(requester="7")
    assert package.status == "active"
    assert package.folder_name == "06-08-2026 14-30"
    assert (tmp_path / "06-08-2026 14-30" / "manifest.json").is_file()
    events = seam.list_audit()
    assert events[0].action == "package.created"
    assert events[0].actor == "7"


def test_complete_active_package_renames_creates_next_and_audits(tmp_path):
    _, seam = make_seam(tmp_path)
    first = seam.ensure_active_package()

    next_package = seam.complete_active_package(requester="9")

    completed_dir = tmp_path / "06-08-2026 14-30-completed"
    assert completed_dir.is_dir()

    assert next_package.status == "active"
    assert next_package.id != first.id
    assert seam.get_active_package() == next_package
    assert (tmp_path / next_package.folder_name / "manifest.json").is_file()

    actions = [e.action for e in seam.list_audit()]
    assert actions[0] == "package.created"  # for the next package
    assert actions[1] == "package.completed"
    completed = [e for e in seam.list_audit() if e.action == "package.completed"]
    assert completed[0].actor == "9"
    assert completed[0].details == {"folder_name": "06-08-2026 14-30-completed"}


def test_complete_active_package_without_active_raises(tmp_path):
    _, seam = make_seam(tmp_path)
    with pytest.raises(NoActivePackage):
        seam.complete_active_package()
    assert len(list(tmp_path.iterdir())) == 0


def test_zero_or_one_invariant_after_completion(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    with pytest.raises(ActivePackageExists):
        seam.ensure_active_package()
    seam.complete_active_package()
    assert seam.get_active_package() is not None
    assert seam.get_active_package().status == "active"
    with pytest.raises(ActivePackageExists):
        seam.ensure_active_package()
