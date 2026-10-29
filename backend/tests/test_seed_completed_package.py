from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from dojo import DojoPublishing, InMemoryStore
from dojo.package_media import describe_artifacts

spec = spec_from_file_location(
    "seed_completed_package", Path(__file__).parents[1] / "scripts/seed_completed_package.py",
)
seed = module_from_spec(spec)
spec.loader.exec_module(seed)


def test_seed_adds_one_playable_archive_without_changing_active_package(tmp_path):
    store = InMemoryStore()
    publishing = DojoPublishing(packages=store, audit=store, settings=store, media_root=tmp_path)
    active = publishing.get_active_package()
    package, created = seed.seed_completed_package(store, tmp_path)
    assert created and package.status == "completed"
    assert store.get_active() == active
    manifest = store.read_package_state(package.id).document
    assert manifest["demo_fixture"] is True
    assert len(manifest["media"]) == 2
    assert manifest["media"][0]["photo_duration_seconds"] == 2.95
    assert all(a["available"] for a in describe_artifacts(tmp_path / package.folder_name, manifest))
    assert seed.seed_completed_package(store, tmp_path) == (package, False)
    assert len(store.list_completed()) == 1


@pytest.mark.parametrize("url", [
    "postgresql+psycopg://user:secret@production.example/db",
    "postgresql+psycopg://user:secret@db/db",
    "sqlite:///local.db",
    "postgresql+psycopg://user:secret@localhost:5434/dojo?host=production.example",
    "postgresql+psycopg://user:secret@localhost:5434/dojo?hostaddr=203.0.113.1",
    "postgresql+psycopg://user:secret@localhost:5434/dojo?service=production",
])
def test_seed_refuses_non_loopback_postgres(url):
    with pytest.raises(ValueError, match="loopback PostgreSQL"):
        seed.require_local_database(url)


@pytest.mark.parametrize("name", ["PGHOSTADDR", "PGSERVICE"])
def test_seed_refuses_environment_connection_overrides(monkeypatch, name):
    monkeypatch.setenv(name, "production")
    with pytest.raises(ValueError, match="loopback PostgreSQL"):
        seed.require_local_database("postgresql+psycopg://user:secret@localhost:5434/dojo")
