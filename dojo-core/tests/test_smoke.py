from __future__ import annotations

import json
from pathlib import Path

from dojo import ActivePackageExists, DojoPublishing
from dojo.adapters.db import PostgresStore
from dojo.adapters.stubs import StubMetaPublisher, StubNotifier, StubSignedUrlStore
from dojo.testing import FakeClock


def test_smoke_ensure_active_package_through_real_seam(
    pg_store: PostgresStore, tmp_path: Path
) -> None:
    seam = DojoPublishing(
        packages=pg_store,
        audit=pg_store,
        media_root=tmp_path,
        clock=FakeClock(),
        meta=StubMetaPublisher(),
        notifier=StubNotifier(),
        signed_urls=StubSignedUrlStore(),
    )

    package = seam.ensure_active_package()

    assert package.folder_name == "06-08-2026 14-30"

    folder = tmp_path / "06-08-2026 14-30"
    assert folder.is_dir()
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["media"] == []
    assert manifest["render_revision"] is None

    active = seam.get_active_package()
    assert active is not None and active.folder_name == "06-08-2026 14-30"

    events = seam.list_audit()
    assert events[0].action == "package.created"

    try:
        seam.ensure_active_package()
        raise AssertionError("expected ActivePackageExists")
    except ActivePackageExists:
        pass
