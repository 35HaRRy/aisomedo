from __future__ import annotations

from datetime import datetime

from dojo import Client, DojoSetup, NoConsentPolicy
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.deps import get_current_client


def get_setup(request: Request) -> DojoSetup:
    return request.app.state.setup


class SetupItemOut(BaseModel):
    key: str
    label: str
    complete: bool


class SetupOut(BaseModel):
    checklist: list[SetupItemOut]
    ready: bool


class ConsentOut(BaseModel):
    version: int
    text: str
    accepted_at: datetime | None


class AcceptanceOut(BaseModel):
    version: int
    accepted_at: datetime


router = APIRouter(prefix="/api/setup", tags=["setup"])


@router.get("", response_model=SetupOut)
def setup_state(
    _client: Client = Depends(get_current_client),
    setup: DojoSetup = Depends(get_setup),
) -> SetupOut:
    return SetupOut(
        checklist=[SetupItemOut(**vars(item)) for item in setup.checklist()],
        ready=setup.is_ready(),
    )


@router.get("/consent", response_model=ConsentOut)
def get_consent(
    _client: Client = Depends(get_current_client),
    setup: DojoSetup = Depends(get_setup),
) -> ConsentOut:
    policy = setup.current_policy()
    if policy is None:
        raise HTTPException(status_code=404, detail="no consent policy configured")
    acceptance = setup.current_acceptance()
    return ConsentOut(
        version=policy.version,
        text=policy.text,
        accepted_at=acceptance.accepted_at if acceptance is not None else None,
    )


@router.post("/consent/accept", response_model=AcceptanceOut)
def accept_consent(
    client: Client = Depends(get_current_client),
    setup: DojoSetup = Depends(get_setup),
) -> AcceptanceOut:
    try:
        acceptance = setup.accept_current_policy(client=client)
    except NoConsentPolicy as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AcceptanceOut(version=acceptance.policy_version, accepted_at=acceptance.accepted_at)
