import json
from dataclasses import replace
from time import monotonic

from dojo.worker_health import current_boot_id
from test_api import make_app


def paired(tmp_path):
    client, publishing, pairing, _ = make_app(tmp_path)
    code = pairing.create_pairing_code(requester="cli").raw_code
    response = client.post("/api/pairing/validate", json={
        "code": code, "kind": "browser", "name": "Tarayıcı",
    })
    assert response.status_code == 200
    return client, publishing, pairing, response.json()["client_id"]


def test_dashboard_cookie_auth_and_revocation(tmp_path):
    client, _, _, _ = make_app(tmp_path)
    assert client.get("/api/dashboard").status_code == 401
    client, publishing, pairing, client_id = paired(tmp_path)
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["package"] is None
    assert body["pending_actions"] == []
    assert body["instagram"]["health"] == "not_connected"
    assert body["worker"]["status"] == "unknown"
    assert publishing.get_active_package() is None
    pairing.revoke_client(client_id=client_id, requester="cli")
    assert client.get("/api/dashboard").status_code == 401


def test_optional_failure_does_not_erase_publishing_package(tmp_path):
    client, publishing, _, _ = paired(tmp_path)
    package = publishing.get_or_create_active_package()
    publishing._packages.update(replace(package, status="publishing"))

    class BrokenMeta:
        def get_status(self):
            raise RuntimeError("secret-provider-token")

    client.app.state.meta = BrokenMeta()
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    assert response.json()["package"]["status"] == "publishing"
    assert response.json()["instagram"]["health"] == "unknown"
    assert "secret-provider-token" not in response.text


def test_expired_busy_worker_is_not_api_liveness(tmp_path, monkeypatch):
    path = tmp_path / "worker.json"
    path.write_text(json.dumps({"version": 1, "phase": "busy", "boot_id": current_boot_id(),
                               "monotonic": monotonic() - 4000, "deadline": monotonic() - 1}))
    monkeypatch.setenv("WORKER_HEALTH_PATH", str(path))
    client, _, _, _ = paired(tmp_path)
    assert client.get("/health").status_code == 200
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    assert response.json()["worker"] == {"status": "unhealthy", "phase": "busy"}
