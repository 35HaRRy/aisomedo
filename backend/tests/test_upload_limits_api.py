from pathlib import Path

from dojo.testing import FakeClock
from test_api import make_app


def test_limits_requires_pairing(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    assert client.get("/api/media/upload-limits").status_code == 401
    code = pairing.create_pairing_code(requester="cli").raw_code
    paired = client.post("/api/pairing/validate", json={
        "code": code, "kind": "browser", "name": "Browser",
    })
    assert client.get("/api/media/upload-limits").status_code == 200
    pairing.revoke_client(client_id=paired.json()["client_id"], requester="cli")
    assert client.get("/api/media/upload-limits").status_code == 401


def test_limits_defaults_and_read_only(tmp_path: Path) -> None:
    client, publishing, pairing, _ = make_app(tmp_path)
    code = pairing.create_pairing_code(requester="cli").raw_code
    client.post("/api/pairing/validate", json={
        "code": code, "kind": "browser", "name": "Browser",
    })
    before = publishing._audit.list_recent()
    response = client.get("/api/media/upload-limits")
    assert response.status_code == 200
    assert response.json() == {"max_file_bytes": 2 * 1024**3, "max_package_bytes": 20 * 1024**3}
    assert publishing.get_active_package() is None
    assert publishing.list_active_uploads() == []
    assert publishing.claim_next_job() is None
    assert publishing._audit.list_recent() == before


def test_limits_configured_values(tmp_path: Path) -> None:
    client, publishing, pairing, _ = make_app(tmp_path)
    code = pairing.create_pairing_code(requester="cli").raw_code
    client.post("/api/pairing/validate", json={
        "code": code, "kind": "browser", "name": "Browser",
    })
    publishing._settings.set("upload.max_file_bytes", 5, updated_at=FakeClock().now())
    publishing._settings.set("upload.max_package_bytes", 100, updated_at=FakeClock().now())
    assert client.get("/api/media/upload-limits").json() == {
        "max_file_bytes": 5, "max_package_bytes": 100,
    }
