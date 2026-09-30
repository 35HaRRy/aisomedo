"""Authenticated, side-effect-free dashboard projection."""

import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Literal

from dojo import DojoPublishing
from dojo.worker_health import read_worker_status
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from backend.routes.packages import PackageOut, get_publishing
from backend.routes.settings import PlanOut

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class DashboardSlotOut(BaseModel):
    kind: str
    due_at: datetime


class DashboardActionOut(BaseModel):
    occurrence_id: int
    review_id: int | None
    version: int | None
    due_at: datetime
    package_folder: str | None
    state: Literal["review_ready", "empty_package", "preparing"]


class DashboardInstagramOut(BaseModel):
    health: str
    username: str | None = None


class DashboardWorkerOut(BaseModel):
    status: Literal["healthy", "unhealthy", "unknown"]
    phase: Literal["idle", "busy", "stopped"] | None


class DashboardOut(BaseModel):
    generated_at: datetime
    package: PackageOut | None
    next_slot: DashboardSlotOut | None
    pending_actions: list[DashboardActionOut]
    plan: PlanOut
    instagram: DashboardInstagramOut
    worker: DashboardWorkerOut


@router.get("", response_model=DashboardOut)
def dashboard(
    request: Request, response: Response,
    publishing: DojoPublishing = Depends(get_publishing),
) -> DashboardOut:
    response.headers["Cache-Control"] = "no-store"
    summary = publishing.get_dashboard_summary()
    instagram = DashboardInstagramOut(health="not_connected")
    meta = getattr(request.app.state, "meta", None)
    if meta is not None:
        try:
            status = meta.get_status()  # persisted connection only; never contacts Meta
            instagram = DashboardInstagramOut(health=status.health, username=status.ig_username)
        except Exception:  # noqa: BLE001 - optional status cannot erase publishing facts
            instagram = DashboardInstagramOut(health="unknown")
    path = os.environ.get("WORKER_HEALTH_PATH")
    reader = getattr(request.app.state, "worker_status_reader", read_worker_status)
    worker = reader(Path(path) if path else None)
    return DashboardOut(
        generated_at=summary.generated_at,
        package=PackageOut(**asdict(summary.package)) if summary.package else None,
        next_slot=DashboardSlotOut(**asdict(summary.next_slot)) if summary.next_slot else None,
        pending_actions=[
            DashboardActionOut(**asdict(action)) for action in summary.pending_actions
        ],
        plan=PlanOut(**summary.plan.to_dict()), instagram=instagram,
        worker=DashboardWorkerOut(**asdict(worker)),
    )
