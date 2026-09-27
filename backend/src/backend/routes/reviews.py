from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from dojo import (
    Client,
    DojoPublishing,
    LogoNotConfigured,
    PublicationInProgress,
    PublicationNotReady,
    RenderFailed,
    RescheduleTimeInvalid,
    ReviewAlreadyHandled,
    ReviewNotFound,
    ReviewStale,
    SkipRequiresConfirmation,
)
from dojo.model import YayinIncelemesi
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.deps import get_current_client


def get_publishing(request: Request) -> DojoPublishing:
    return request.app.state.publishing


router = APIRouter(prefix="/api/reviews", tags=["reviews"])


def _review_out(review: YayinIncelemesi) -> dict[str, object]:
    return asdict(review)


@router.get("/pending", response_model=dict[str, object])
def list_pending(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    return {"reviews": [_review_out(r) for r in publishing.list_pending_reviews()]}


class ApproveIn(BaseModel):
    version: int


@router.post("/{review_id}/approve", response_model=dict[str, object])
def approve_review(
    review_id: int,
    body: ApproveIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    try:
        review = publishing.approve(review_id, body.version, requester=str(client.id))
    except ReviewNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ReviewStale, ReviewAlreadyHandled, PublicationInProgress) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (PublicationInProgress, PublicationNotReady) as exc:
        # fresh publish prohibited while another publication reconciles
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (LogoNotConfigured, RenderFailed) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"review": _review_out(review), "publication": publishing.get_publication_status()}


class SkipIn(BaseModel):
    version: int
    confirmed: bool = False


@router.post("/{review_id}/skip", response_model=dict[str, object])
def skip_review(
    review_id: int,
    body: SkipIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    try:
        result = publishing.skip(
            review_id, body.version, confirmed=body.confirmed, requester=str(client.id)
        )
    except ReviewNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ReviewStale, ReviewAlreadyHandled, PublicationInProgress) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SkipRequiresConfirmation as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    out = _review_out(result.review)
    nxt = result.next_regular_at
    return {"review": out, "next_regular_at": nxt.isoformat() if isinstance(nxt, datetime) else nxt}


class RescheduleIn(BaseModel):
    version: int
    new_due_at: datetime


@router.post("/{review_id}/reschedule", response_model=dict[str, object])
def reschedule_review(
    review_id: int,
    body: RescheduleIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    try:
        review = publishing.reschedule(
            review_id, body.version, body.new_due_at, requester=str(client.id)
        )
    except ReviewNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ReviewStale, ReviewAlreadyHandled, PublicationInProgress) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RescheduleTimeInvalid as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"review": _review_out(review)}
