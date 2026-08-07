from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

ISTANBUL = ZoneInfo("Europe/Istanbul")


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(tz=ISTANBUL)
