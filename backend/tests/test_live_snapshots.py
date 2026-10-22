from concurrent.futures import ThreadPoolExecutor

import pytest
from dojo.adapters.db import PostgresStore
from dojo.live import PackageState
from dojo.model import Package
from dojo.testing import FIXED_AT
from test_live_events import live_store  # noqa: F401 - share the real database fixture
from test_package_editor_api import app


@pytest.mark.parametrize("path,key", [
    ("/api/dashboard", "dashboard"),
    ("/api/setup", "setup"),
    ("/api/setup/consent", "setup"),
    ("/api/activity", "activity"),
    ("/api/settings/branding", "settings"),
    ("/api/settings/plan", "settings"),
    ("/api/settings/reminders", "settings"),
    ("/api/packages", "completed"),
    ("/api/packages/active/editor", "package:1"),
    ("/api/packages/active/montage", "package:1"),
    ("/api/packages/active/caption", "package:1"),
    ("/api/packages/active/branding", "package:1"),
    ("/api/reviews/pending", "publication"),
    ("/api/packages/active/publication", "publication"),
    ("/api/media/uploads", "dashboard"),
])
def test_displayed_reads_include_committed_resource_version(tmp_path, path, key):
    client, publishing, _, _, _ = app(tmp_path)
    client.app.state.setup.set_policy(version=1, text="policy", requester="cli")
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers.get("X-Resource-Key") == key
    assert response.headers.get("X-Resource-Version") == str(
        publishing._packages.get_resource_version(key),
    )


def test_read_boundary_keeps_data_and_version_on_same_snapshot_across_stores(live_store):  # noqa: F811
    writer = live_store
    package = writer.create(Package(0, "snapshot", FIXED_AT))
    key = f"package:{package.id}"
    with writer.command_transaction():
        first = writer.write_package_state(package.id, {"caption": "first"}, content_changed=True)
        before = writer.record_change([key]).versions[key]
    reader = PostgresStore(writer._engine.url.render_as_string(hide_password=False))
    sibling = PostgresStore(writer._engine.url.render_as_string(hide_password=False))
    try:
        with reader.read_snapshot():
            assert reader.get_resource_version(key) == before
            def commit():
                with writer.command_transaction():
                    writer.write_package_state(package.id, {"caption": "second"},
                                               content_changed=True)
                    writer.record_change([key])
            with ThreadPoolExecutor(1) as pool:
                pool.submit(commit).result(timeout=5)
            # A different facade/adapter used by the same endpoint must join
            # the snapshot too, rather than mixing new Meta/setup with old data.
            state: PackageState = sibling.read_package_state(package.id)
            assert state == first
            assert reader.get_resource_version(key) == before
        assert reader.read_package_state(package.id).document == {"caption": "second"}
        assert reader.get_resource_version(key) == before + 1
    finally:
        reader.dispose()
        sibling.dispose()
