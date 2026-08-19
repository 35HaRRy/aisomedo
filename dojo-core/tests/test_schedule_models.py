from __future__ import annotations

from datetime import date, time

from dojo import ManualPublishConflict, PlanInvalid, SchedulePlan, YayinZamani
from dojo.exceptions import DojoError
from dojo.testing import FIXED_AT


def test_schedule_plan_to_dict() -> None:
    plan = SchedulePlan(
        anchor_date=date(2026, 8, 3),
        anchor_time=time(10, 0),
        enabled=True,
    )
    assert plan.to_dict() == {
        "anchor_date": "2026-08-03",
        "anchor_time": "10:00:00",
        "enabled": True,
        "timezone": "Europe/Istanbul",
    }


def test_schedule_plan_defaults() -> None:
    plan = SchedulePlan()
    assert plan.anchor_date is None
    assert plan.anchor_time is None
    assert plan.enabled is True


def test_exceptions_are_dojo_errors() -> None:
    assert issubclass(PlanInvalid, DojoError)
    assert issubclass(ManualPublishConflict, DojoError)


def test_yayin_zamani_defaults() -> None:
    occ = YayinZamani(
        id=1, kind="regular", due_at=FIXED_AT, status="pending", created_at=FIXED_AT
    )
    assert occ.resolved_at is None