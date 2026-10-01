from __future__ import annotations

from pathlib import Path

import dojo
import pytest

from tests.test_branding import load_manifest, make_seam, set_defaults


def test_caption_patch_preserves_logo_and_cards(tmp_path: Path) -> None:
    store, seam = make_seam(tmp_path)
    before = set_defaults(seam)
    result = seam.patch_branding_defaults({"caption_template": "Yeni metin"}, requester="1")
    assert result.logo_asset == before.logo_asset
    assert result.intro_asset == before.intro_asset
    assert result.outro_duration == 3.0
    assert result.caption_template == "Yeni metin"
    audits = [e for e in store.list_recent() if e.actor == "1"]
    assert len(audits) == 1
    assert audits[0].details["caption_template"] == "Yeni metin"


def test_null_card_clears_asset_and_duration(tmp_path: Path) -> None:
    _, seam = make_seam(tmp_path)
    set_defaults(seam)
    result = seam.patch_branding_defaults({"intro_asset": None})
    assert result.intro_asset is None
    assert result.intro_duration is None
    assert result.outro_asset == "outro.mp4"


def test_patch_preserves_existing_package_snapshot(tmp_path: Path) -> None:
    _, seam = make_seam(tmp_path)
    set_defaults(seam)
    seam.get_or_create_active_package()
    before = load_manifest(tmp_path, seam)
    seam.patch_branding_defaults({"caption_template": "New", "logo_asset": "new.png"})
    assert load_manifest(tmp_path, seam) == before


@pytest.mark.parametrize("changes", [
    {"caption_template": " \n "}, {"logo_asset": ""}, {"unknown": "x"},
    {"intro_duration": -1}, {"intro_duration": 0}, {"intro_duration": float("nan")},
    {"intro_duration": float("inf")}, {"outro_duration": True}, {"logo_asset": 7},
    {"outro_duration": "2"},
])
def test_invalid_patch_does_not_write(tmp_path: Path, changes: dict[str, object]) -> None:
    _, seam = make_seam(tmp_path)
    before = set_defaults(seam)
    with pytest.raises(dojo.BrandingInvalid):
        seam.patch_branding_defaults({"caption_template": "Changed", **changes})
    assert seam.get_branding_defaults() == before


def test_default_duration_and_positive_decimal_are_supported(tmp_path: Path) -> None:
    _, seam = make_seam(tmp_path)
    result = seam.patch_branding_defaults({"intro_asset": "intro.png"})
    assert result.intro_duration is None
    result = seam.patch_branding_defaults({"intro_duration": 1.5})
    assert result.intro_duration == 1.5
