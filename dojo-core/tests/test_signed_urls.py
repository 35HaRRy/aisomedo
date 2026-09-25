from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from dojo.adapters.signed_urls import HmacSignedUrlStore
from dojo.testing import FIXED_AT, FakeClock


def make_store(tmp_path: Path, **overrides):
    render = tmp_path / "pkg" / "render"
    render.mkdir(parents=True)
    artifact = render / "reel.mp4"
    artifact.write_bytes(b"reel")
    raw = tmp_path / "pkg" / "media" / "m1" / "processed.jpg"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"raw")
    store = HmacSignedUrlStore(
        base_url="https://example.test", secret="s3cret", clock=FakeClock(), **overrides
    )
    return store, artifact, raw


def test_create_resolve_revoke_roundtrip(tmp_path):
    store, artifact, _ = make_store(tmp_path)
    url = store.create(artifact)
    assert url.startswith("https://example.test/pub/")
    assert store.resolve(url) == artifact
    store.revoke(url)
    with pytest.raises(ValueError):
        store.resolve(url)


def test_raw_media_paths_denied(tmp_path):
    store, _, raw = make_store(tmp_path)
    with pytest.raises(ValueError):
        store.create(raw)
    with pytest.raises(ValueError):
        store.create(tmp_path / "pkg" / "manifest.json")


def test_expired_url_denied(tmp_path):
    clock = FakeClock(FIXED_AT)
    store, artifact, _ = make_store(tmp_path)
    store._clock = clock
    url = store.create(artifact)
    clock._now = FIXED_AT + timedelta(hours=2)
    with pytest.raises(ValueError):
        store.resolve(url)


def test_unknown_token_denied(tmp_path):
    store, _, _ = make_store(tmp_path)
    with pytest.raises(ValueError):
        store.resolve("https://example.test/pub/nope")
