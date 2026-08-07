from __future__ import annotations

import json

import pytest
from dojo import (
    ActivePackageExists,
    DojoPublishing,
    InMemoryStore,
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
        "caption": None,
        "branding": {},
        "render_revision": None,
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


def test_stubbed_methods_raise_not_implemented(tmp_path):
    _, seam = make_seam(tmp_path)
    for method in ("add_media", "resolve_conflict", "publish", "approve"):
        with pytest.raises(NotImplementedError):
            getattr(seam, method)()
