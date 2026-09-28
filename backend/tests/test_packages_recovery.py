from __future__ import annotations

import json
from pathlib import Path

from test_api import bearer, make_app, pair_device


def seed_recovered(tmp_path: Path, name: str = "05-08-2026 14-30-recovered") -> None:
    folder = tmp_path / name
    entry = folder / "media" / "rec-0"
    entry.mkdir(parents=True, exist_ok=True)
    (entry / "a.jpg").write_bytes(b"q" * 10)
    manifest = {
        "media": [
            {
                "media_id": "rec-0",
                "filename": "a.jpg",
                "content_type": "image/jpeg",
                "size_bytes": 10,
                "uploaded_at": "2026-08-06T14:30:00+03:00",
                "status": "finalized",
                "processed": {},
            }
        ],
        "order": ["rec-0"],
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_recovered_routes_list_import_resolve(tmp_path: Path) -> None:
    client, publishing, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    assert client.post("/api/packages/active", headers=bearer(token)).status_code == 201
    seed_recovered(tmp_path)

    listed = client.get("/api/packages/recovered", headers=bearer(token))
    assert listed.status_code == 200
    assert listed.json()["recovered"] == ["05-08-2026 14-30-recovered"]

    imported = client.post(
        "/api/packages/recovered/05-08-2026 14-30-recovered/import", headers=bearer(token)
    )
    assert imported.status_code == 200
    assert imported.json()["imported"] == 1

    resolved = client.post(
        "/api/packages/recovered/05-08-2026 14-30-recovered/resolve", headers=bearer(token)
    )
    assert resolved.status_code == 200
    assert resolved.json()["resolved"] == "05-08-2026 14-30-resolved"

    again = client.post(
        "/api/packages/recovered/05-08-2026 14-30-recovered/resolve", headers=bearer(token)
    )
    assert again.status_code in (404, 409)
