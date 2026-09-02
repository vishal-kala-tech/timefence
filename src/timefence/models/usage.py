"""SQLite row shapes for screen-time. Separate from JSON `usage.py` state.

`DailyUsage` is the day's total. `SessionRecord` is one foreground stretch
(`ended_at` None = still open). `TodayUsage` / `UsageSnapshot` are read models
for remaining time and the current session.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DailyUsage:
    resource_id: str
    date: str
    total_active_seconds: int
    updated_at: str


@dataclass(frozen=True)
class SessionRecord:
    id: Optional[int]
    resource_id: str
    started_at: str
    ended_at: Optional[str] = None
    duration_seconds: int = 0
    activity_kind: str = "app"
    identifier: str = ""


@dataclass(frozen=True)
class TodayUsage:
    resource_id: str
    used_seconds: int
    used_minutes: int
    limit_seconds: int
    remaining_seconds: int
    currently_active: bool
    current_session_seconds: int

    def to_dict(self):
        return {
            "resource_id": self.resource_id,
            "used_seconds": self.used_seconds,
            "used_minutes": self.used_minutes,
            "limit_seconds": self.limit_seconds,
            "remaining_seconds": self.remaining_seconds,
            "currently_active": self.currently_active,
            "current_session_seconds": self.current_session_seconds,
        }


@dataclass(frozen=True)
class UsageSnapshot:
    resource_id: str
    date: str
    total_active_seconds: int
    current_session_seconds: int
    current_session_start: Optional[str]
    last_seen_timestamp: Optional[str]
    is_currently_active: bool

    def to_dict(self):
        return {
            "resource_id": self.resource_id,
            "date": self.date,
            "total_active_seconds": self.total_active_seconds,
            "current_session_seconds": self.current_session_seconds,
            "current_session_start": self.current_session_start,
            "last_seen_timestamp": self.last_seen_timestamp,
            "is_currently_active": self.is_currently_active,
        }
