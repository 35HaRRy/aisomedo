"""Authenticated, side-effect-free dashboard projection."""

import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Literal

from dojo import (
    Client,
    DojoPublishing,
    OccurrenceChanged,
    OccurrenceNotFound,
    RescheduleTimeInvalid,
    SkipRequiresConfirmation,
)
from dojo.worker_health import read_worker_status
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import AwareDatetime, BaseModel

from backend.deps import get_current_client
from backend.routes.packages import PackageOut, get_publishing
from backend.routes.settings import PlanOut
from backend.snapshots import versioned_snapshot

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class DashboardSlotOut(BaseModel):
    kind: str
    due_at: datetime
    occurrence_id: int | None = None


class OneoffDateIn(BaseModel):
    expected_due_at: datetime
    new_due_at: datetime


class OneoffDecisionIn(BaseModel):
    expected_due_at: AwareDatetime
    action: Literal["review", "skip"]
    confirmed: bool = False


class OneoffDecisionOut(BaseModel):
    occurrence_id: int
    due_at: datetime
    status: str
    package_folder: str | None


@router.post("/occurrences/{occurrence_id}/decision", response_model=OneoffDecisionOut)
def decide_oneoff(
    occurrence_id: int, body: OneoffDecisionIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    try:
        return publishing.decide_oneoff(
            occurrence_id, body.expected_due_at, body.action,
            confirmed=body.confirmed, requester=str(client.id),
        )
    except OccurrenceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OccurrenceChanged as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SkipRequiresConfirmation as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/occurrences/{occurrence_id}", response_model=DashboardSlotOut)
def change_oneoff_date(
    occurrence_id: int, body: OneoffDateIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> DashboardSlotOut:
    try:
        occurrence = publishing.change_oneoff_date(
            occurrence_id, body.expected_due_at, body.new_due_at, requester=str(client.id),
        )
    except OccurrenceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OccurrenceChanged as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RescheduleTimeInvalid as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DashboardSlotOut(
        kind=occurrence.kind, due_at=occurrence.due_at, occurrence_id=occurrence.id,
    )


class DashboardActionOut(BaseModel):
    occurrence_id: int
    review_id: int | None
    version: int | None
    due_at: datetime
    package_folder: str | None
    state: Literal["review_ready", "empty_package", "preparing"]
    review_status: str | None = None


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
    manual_review_allowed: bool = True
    next_slots: list[DashboardSlotOut] | None = None


@router.get("", response_model=DashboardOut)
@versioned_snapshot("dashboard")
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
        manual_review_allowed=summary.manual_review_allowed,
        next_slots=[DashboardSlotOut(**asdict(slot)) for slot in summary.next_slots],
    )
