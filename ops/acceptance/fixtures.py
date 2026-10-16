"""Strict, isolated external services used only by deployed acceptance tests."""

from __future__ import annotations

import hashlib
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict


class ClockInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    now: AwareDatetime


class NotificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notification: dict[str, Any]
    tokens: list[str]


def create_app(*, initial_time: datetime, ca_file: Path) -> FastAPI:
    if initial_time.tzinfo is None:
        raise ValueError("fixture clock must be timezone-aware")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    lock = threading.RLock()
    now = initial_time
    containers: list[dict[str, Any]] = []
    publications: list[dict[str, str]] = []
    notifications: list[dict[str, Any]] = []

    @app.get("/clock")
    def clock() -> dict[str, str]:
        with lock:
            return {"now": now.isoformat()}

    @app.post("/clock")
    def advance(value: ClockInput) -> dict[str, str]:
        nonlocal now
        with lock:
            if value.now < now:
                raise HTTPException(422, "clock cannot move backwards")
            now = value.now
            return {"now": now.isoformat()}

    @app.post("/notifications")
    def collect(value: NotificationInput) -> dict[str, bool]:
        with lock:
            notifications.append(value.model_dump())
        return {"accepted": True}

    @app.get("/evidence")
    def evidence() -> dict[str, Any]:
        with lock:
            return {"now": now.isoformat(), "containers": list(containers),
                    "publications": list(publications), "notifications": list(notifications)}

    async def form(request: Request, fields: set[str]) -> dict[str, str]:
        raw = parse_qs((await request.body()).decode(), keep_blank_values=True)
        if set(raw) != fields or any(len(v) != 1 for v in raw.values()):
            raise HTTPException(422, "unexpected Graph payload")
        values = {key: value[0] for key, value in raw.items()}
        if values["access_token"] != "acceptance-token":
            raise HTTPException(401, "invalid fixture credentials")
        return values

    @app.post("/v26.0/ig_123/media")
    async def ingest(request: Request) -> dict[str, str]:
        values = await form(request, {"media_type", "video_url", "caption", "access_token"})
        url = urlsplit(values["video_url"])
        if (values["media_type"] != "REELS" or url.scheme != "https"
                or url.netloc != "dojo.acceptance.test" or not url.path.startswith("/pub/")):
            raise HTTPException(422, "unexpected video target")
        try:
            response = httpx.get(values["video_url"], verify=str(ca_file), timeout=30,
                                 trust_env=False)
            response.raise_for_status()
            if not response.content:
                raise ValueError("empty video")
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "signed video ingestion failed") from None
        with lock:
            cid = f"container-{len(containers) + 1}"
            containers.append({"id": cid, "caption": values["caption"],
                               "bytes": len(response.content),
                               "sha256": hashlib.sha256(response.content).hexdigest()})
        return {"id": cid}

    @app.get("/v26.0/{container_id}")
    def status(container_id: str, fields: str, access_token: str) -> dict[str, str]:
        if fields != "status_code" or access_token != "acceptance-token":
            raise HTTPException(422, "unexpected status request")
        with lock:
            if not any(item["id"] == container_id for item in containers):
                raise HTTPException(404, "unknown container")
        return {"status_code": "FINISHED"}

    @app.post("/v26.0/ig_123/media_publish")
    async def publish(request: Request) -> dict[str, str]:
        values = await form(request, {"creation_id", "access_token"})
        with lock:
            if not any(item["id"] == values["creation_id"] for item in containers):
                raise HTTPException(404, "container not ingested")
            mid = f"media-{len(publications) + 1}"
            publications.append({"id": mid, "container_id": values["creation_id"]})
        return {"id": mid}

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_app(initial_time=datetime.fromisoformat("2026-10-19T06:59:00+03:00"),
                           ca_file=Path(os.environ["ACCEPTANCE_CA_FILE"])),
                host="0.0.0.0", port=8000, access_log=False)
