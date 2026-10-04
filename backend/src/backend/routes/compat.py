from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from backend.versions import resolve_version_policy

router = APIRouter(prefix="/api/compat", tags=["compat"])


class CompatInfo(BaseModel):
    api_version: str
    android_min_version_code: int
    android_current_version_code: int
    update_url: str


@router.get("", response_model=CompatInfo)
def compat(request: Request) -> dict:
    policy = getattr(request.app.state, "version_policy", None)
    if policy is None:
        policy = resolve_version_policy()
    return {
        "api_version": request.app.version,
        "android_min_version_code": policy.min_version_code,
        "android_current_version_code": policy.current_version_code,
        "update_url": policy.update_url,
    }
