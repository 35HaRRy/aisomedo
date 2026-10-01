"""Read-only publishing dashboard values and recurrence selection."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from dojo.model import Package, SchedulePlan, YayinZamani


@dataclass(frozen=True)
class NextSlot:
    kind: str
    due_at: datetime


@dataclass(frozen=True)
class PendingAction:
    occurrence_id: int
    review_id: int | None
    version: int | None
    due_at: datetime
    package_folder: str | None
    state: Literal["review_ready", "empty_package", "preparing"]


@dataclass(frozen=True)
class PublishingDashboard:
    generated_at: datetime
    package: Package | None
    next_slot: NextSlot | None
    pending_actions: list[PendingAction]
    plan: SchedulePlan


def next_slot(
    plan: SchedulePlan, occurrences: list[YayinZamani], now: datetime,
) -> NextSlot | None:
    candidates = [
        NextSlot(o.kind, o.due_at) for o in occurrences
        if o.kind in ("manual", "oneoff") and o.status == "pending" and o.due_at > now
    ]
    if plan.enabled and plan.anchor_date is not None and plan.anchor_time is not None:
        anchor = datetime.combine(plan.anchor_date, plan.anchor_time, ZoneInfo(plan.timezone))
        interval = timedelta(days=14)
        steps = max(0, (now - anchor) // interval + 1)
        due = anchor + steps * interval
        resolved = {o.due_at for o in occurrences if o.kind == "regular" and o.status == "resolved"}
        while due in resolved:
            due += interval
        candidates.append(NextSlot("regular", due))
    return min(candidates, key=lambda slot: slot.due_at, default=None)
