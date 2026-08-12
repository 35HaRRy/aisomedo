from __future__ import annotations

from datetime import datetime

from dojo import DojoActivity
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel


def get_activity(request: Request) -> DojoActivity:
    return request.app.state.activity


class ClientRefOut(BaseModel):
    id: int
    name: str
    kind: str


class ActivityEventOut(BaseModel):
    id: int
    action: str
    occurred_at: datetime
    details: dict
    actor: ClientRefOut | str


class ActivityPageOut(BaseModel):
    events: list[ActivityEventOut]
    next_cursor: int | None


router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("", response_model=ActivityPageOut)
def list_activity(
    activity: DojoActivity = Depends(get_activity),
    limit: int = Query(50, ge=1, le=100),
    before_id: int | None = Query(None),
) -> ActivityPageOut:
    page = activity.list_activity(limit=limit, before_id=before_id)
    events = [
        ActivityEventOut(
            id=e.id,
            action=e.action,
            occurred_at=e.occurred_at,
            details=e.details,
            actor=(
                e.actor
                if isinstance(e.actor, str)
                else ClientRefOut(id=e.actor.id, name=e.actor.name, kind=e.actor.kind)
            ),
        )
        for e in page.entries
    ]
    return ActivityPageOut(events=events, next_cursor=page.next_cursor)