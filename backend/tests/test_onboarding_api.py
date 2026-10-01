from pathlib import Path

from test_api import bearer, make_app, pair_device


def test_versioned_consent_rejects_stale_without_accepting_new_policy(tmp_path: Path) -> None:
    client, _, pairing, setup = make_app(tmp_path)
    headers = bearer(pair_device(client, pairing))
    setup.set_policy(version=1, text="v1", requester="cli")
    setup.set_policy(version=2, text="v2", requester="cli")
    response = client.post("/api/setup/consent/accept", headers=headers, json={"version": 1})
    assert response.status_code == 409
    assert client.get("/api/setup/consent", headers=headers).json()["accepted_at"] is None
    accepted = client.post("/api/setup/consent/accept", headers=headers, json={"version": 2})
    assert accepted.status_code == 200
    assert client.post("/api/setup/consent/accept", headers=headers).json() == accepted.json()


def test_setup_exposes_required_flags_and_persists_card_skip(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    headers = bearer(pair_device(client, pairing))
    assert client.post("/api/setup/cards/skip").status_code == 401
    before = client.get("/api/setup", headers=headers).json()
    assert len(before["checklist"]) == 7
    assert before["checklist"][-1]["required"] is False
    response = client.post("/api/setup/cards/skip", headers=headers)
    assert response.status_code == 200
    assert response.json()["checklist"][-1]["complete"] is True
    assert client.get("/api/setup", headers=headers).json()["checklist"][-1]["complete"] is True
    assert response.json()["ready"] is False


def test_caption_patch_preserves_legacy_branding(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    headers = bearer(pair_device(client, pairing))
    client.put("/api/settings/branding", headers=headers, json={"logo_asset": "legacy.png"})
    response = client.patch(
        "/api/settings/branding", headers=headers, json={"caption_template": "New text"}
    )
    assert response.status_code == 200
    assert response.json()["logo_asset"] == "legacy.png"
    assert response.json()["caption_template"] == "New text"
    for changes in (
        {"logo_asset": "C:/secret.png"},
        {"caption_template": "  "},
        {"intro_duration": True},
        {"other": "value"},
    ):
        assert (
            client.patch("/api/settings/branding", headers=headers, json=changes).status_code == 422
        )
    assert client.get("/api/settings/branding", headers=headers).json() == response.json()


def test_missing_meta_is_sanitized_configuration_error(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    client.app.state.meta = None
    headers = bearer(pair_device(client, pairing))
    for path, body in (
        ("/api/meta/instagram/token", {"access_token": "secret-token"}),
        ("/api/meta/oauth/start", {}),
    ):
        response = client.post(path, headers=headers, json=body)
        assert response.status_code == 503
        assert "secret-token" not in response.text
