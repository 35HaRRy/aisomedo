from __future__ import annotations

import json

import pytest
from dojo import (
    BrandingConfig,
    DojoPublishing,
    InMemoryStore,
    LogoNotConfigured,
    NoActivePackage,
)
from dojo.adapters.stubs import (
    StubMetaPublisher,
    StubNotifier,
    StubSignedUrlStore,
)
from dojo.testing import FakeClock


def make_seam(tmp_path, **overrides):
    store = InMemoryStore()
    return (
        store,
        DojoPublishing(
            packages=store,
            audit=store,
            uploads=store,
            jobs=store,
            settings=store,
            media_root=tmp_path,
            clock=FakeClock(),
            meta=StubMetaPublisher(),
            notifier=StubNotifier(),
            signed_urls=StubSignedUrlStore(),
            **overrides,
        ),
    )


def load_manifest(tmp_path, seam):
    package = seam.get_active_package()
    return json.loads(
        (tmp_path / package.folder_name / "manifest.json").read_text(encoding="utf-8")
    )


def set_defaults(seam, **overrides):
    base = {
        "logo_asset": "logo.png",
        "intro_asset": "intro.mp4",
        "intro_duration": 2.0,
        "outro_asset": "outro.mp4",
        "outro_duration": 3.0,
        "caption_template": "Bugün dojoda {{isim}}",
    }
    base.update(overrides)
    return seam.set_branding_defaults(BrandingConfig(**base), requester="cli")


def test_get_branding_defaults_empty_by_default(tmp_path):
    _, seam = make_seam(tmp_path)
    config = seam.get_branding_defaults()
    assert config.logo_asset is None
    assert config.caption_template is None


def test_set_branding_defaults_persists_and_audits(tmp_path):
    store, seam = make_seam(tmp_path)
    config = set_defaults(seam)
    assert config.logo_asset == "logo.png"
    assert config.caption_template == "Bugün dojoda {{isim}}"
    actions = [e.action for e in seam.list_audit()]
    assert actions[0] == "branding.defaults_updated"
    assert seam.list_audit()[0].actor == "cli"
    assert store.get("branding.logo_asset") == "logo.png"


def test_create_package_seeds_draft_defaults(tmp_path):
    _, seam = make_seam(tmp_path)
    set_defaults(seam)
    seam.get_or_create_active_package()
    manifest = load_manifest(tmp_path, seam)
    assert manifest["branding"]["logo_asset"] == "logo.png"
    assert manifest["branding"]["intro_asset"] == "intro.mp4"
    assert manifest["branding"]["intro_duration"] == 2.0
    assert manifest["caption"] == "Bugün dojoda {{isim}}"


def test_create_package_without_defaults_seeds_empty(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.get_or_create_active_package()
    manifest = load_manifest(tmp_path, seam)
    assert manifest["branding"]["logo_asset"] is None
    assert manifest["caption"] is None


def test_complete_creates_next_package_with_defaults(tmp_path):
    _, seam = make_seam(tmp_path)
    set_defaults(seam)
    seam.get_or_create_active_package()
    seam.complete_active_package(requester="9")
    manifest = load_manifest(tmp_path, seam)
    assert manifest["branding"]["logo_asset"] == "logo.png"
    assert manifest["caption"] == "Bugün dojoda {{isim}}"


def test_set_caption_overrides_draft_only(tmp_path):
    _, seam = make_seam(tmp_path)
    set_defaults(seam)
    seam.get_or_create_active_package()
    seam.set_caption("Özel açıklama", requester="7")
    manifest = load_manifest(tmp_path, seam)
    assert manifest["caption"] == "Özel açıklama"
    assert seam.get_branding_defaults().caption_template == "Bugün dojoda {{isim}}"
    actions = [e.action for e in seam.list_audit()]
    assert actions[0] == "caption.draft_updated"
    assert seam.list_audit()[0].actor == "7"


def test_set_branding_overrides_draft_only(tmp_path):
    _, seam = make_seam(tmp_path)
    set_defaults(seam)
    seam.get_or_create_active_package()
    seam.set_branding({"intro_asset": "custom.mp4", "outro_duration": 5.0}, requester="8")
    manifest = load_manifest(tmp_path, seam)
    assert manifest["branding"]["intro_asset"] == "custom.mp4"
    assert manifest["branding"]["outro_duration"] == 5.0
    # logo still seeded, untouched
    assert manifest["branding"]["logo_asset"] == "logo.png"
    assert seam.get_branding_defaults().intro_asset == "intro.mp4"
    actions = [e.action for e in seam.list_audit()]
    assert actions[0] == "branding.draft_updated"
    assert seam.list_audit()[0].actor == "8"


def test_caption_template_fields_pass_through_opaque(tmp_path):
    _, seam = make_seam(tmp_path)
    text = "Bugün {{ogrenci}} {koç} #dojo\nİkinci satır"
    seam.set_branding_defaults(BrandingConfig(caption_template=text), requester="cli")
    seam.get_or_create_active_package()
    assert load_manifest(tmp_path, seam)["caption"] == text
    # edits preserve arbitrary placeholder vocabulary
    edited = "{{any_field}} başka {{2}}"
    seam.set_caption(edited)
    assert load_manifest(tmp_path, seam)["caption"] == edited


def test_caption_and_branding_edits_clear_render_revision(tmp_path):
    _, seam = make_seam(tmp_path)
    set_defaults(seam)
    seam.get_or_create_active_package()
    manifest_path = tmp_path / seam.get_active_package().folder_name / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["render_revision"] = "rev-1"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    seam.set_caption("x")
    assert load_manifest(tmp_path, seam)["render_revision"] is None

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["render_revision"] = "rev-2"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    seam.set_branding({"intro_asset": "y.mp4"})
    assert load_manifest(tmp_path, seam)["render_revision"] is None


def test_publish_without_logo_raises(tmp_path):
    _, seam = make_seam(tmp_path)
    seam.get_or_create_active_package()
    with pytest.raises(LogoNotConfigured):
        seam.publish()


def test_publish_with_logo_passes_guard(tmp_path):
    _, seam = make_seam(tmp_path)
    set_defaults(seam)
    seam.get_or_create_active_package()
    with pytest.raises(NotImplementedError):
        seam.publish()


def test_branding_without_active_package_raises(tmp_path):
    _, seam = make_seam(tmp_path)
    with pytest.raises(NoActivePackage):
        seam.get_draft_branding()
    with pytest.raises(NoActivePackage):
        seam.get_draft_caption()
    with pytest.raises(NoActivePackage):
        seam.set_caption("x")
    with pytest.raises(NoActivePackage):
        seam.set_branding({})


def test_get_draft_branding_and_caption(tmp_path):
    _, seam = make_seam(tmp_path)
    set_defaults(seam)
    seam.get_or_create_active_package()
    assert seam.get_draft_branding()["logo_asset"] == "logo.png"
    assert seam.get_draft_caption() == "Bugün dojoda {{isim}}"