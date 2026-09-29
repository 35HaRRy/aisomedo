from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/ready")
def ready(request: Request) -> JSONResponse:
    check = getattr(request.app.state, "readiness", None)
    if not callable(check):
        return JSONResponse({"status": "unavailable"}, status_code=503)
    try:
        healthy = bool(check())
    except Exception:  # noqa: BLE001 - any probe error means "not available"
        return JSONResponse({"status": "unavailable"}, status_code=503)
    if healthy:
        return JSONResponse({"status": "ok"}, status_code=200)
    return JSONResponse({"status": "unavailable"}, status_code=503)
