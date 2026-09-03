from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from ..models.usage import DailyUsage, SessionRecord


class UsageStore(ABC):
    """Persistence for screen-time totals and sessions.

    `UsageTracker` depends on this interface, not SQLite, so tests can inject
    a fake store and a later backend can replace the file without rewriting
    accounting rules.

    Daily totals are keyed by local date string (`YYYY-MM-DD`). Window totals
    are keyed by the `allowed_windows[].id` from rules.json for that same date.
    Browse visits are the frontmost-browser tab log (including YouTube URLs).
    Watch rows are YouTube/Shorts videos. Open sessions have `ended_at IS NULL`.
    `record_warning` is idempotent per (day, resource, key).
    """

    @abstractmethod
    def add_active_seconds(self, usage_date: str, resource_id: str, seconds: int, updated_at: str) -> int:
        """Atomically add seconds to the day's total. Returns the new total."""

    @abstractmethod
    def get_daily(self, usage_date: str, resource_id: str) -> Optional[DailyUsage]:
        pass

    @abstractmethod
    def get_all_daily(self, usage_date: str) -> List[DailyUsage]:
        pass

    @abstractmethod
    def add_window_seconds(
        self, usage_date: str, resource_id: str, window_id: str, seconds: int, updated_at: str
    ) -> int:
        """Atomically add seconds to a day's window total. Returns the new window total."""

    @abstractmethod
    def get_windows(self, usage_date: str, resource_id: str) -> Dict[str, int]:
        """Map window_id → usage_seconds for that resource and date."""

    @abstractmethod
    def start_session(
        self,
        resource_id: str,
        started_at: str,
        activity_kind: str = "app",
        identifier: str = "",
    ) -> int:
        pass

    @abstractmethod
    def update_session(self, session_id: int, duration_seconds: int, ended_at: Optional[str] = None) -> None:
        pass

    @abstractmethod
    def end_session(self, session_id: int, ended_at: str, duration_seconds: int) -> None:
        pass

    @abstractmethod
    def get_open_session(self, resource_id: str) -> Optional[SessionRecord]:
        pass

    @abstractmethod
    def get_open_sessions(self) -> List[SessionRecord]:
        pass

    @abstractmethod
    def record_warning(self, usage_date: str, resource_id: str, warning_key: str) -> bool:
        """Persist a per-day warning key. Returns True if this is the first time it was recorded."""

    @abstractmethod
    def has_warning(self, usage_date: str, resource_id: str, warning_key: str) -> bool:
        pass

    @abstractmethod
    def add_browse_visit(
        self,
        usage_date: str,
        host: str,
        url: str,
        title: str,
        seconds: int,
        seen_at: str,
        browser: str = "",
        max_rows: int = 5000,
    ) -> str:
        """Insert or extend today's last visit when the URL matches.

        Returns `inserted`, `updated`, `full`, or `skipped`.
        """

    @abstractmethod
    def get_browse_visits(self, usage_date: str) -> List[dict]:
        """Front-tab visits for that date, in the order they were recorded."""

    @abstractmethod
    def seed_browse_visits(self, usage_date: str, visits) -> None:
        """Copy legacy JSON visits into SQLite when that date has no rows yet."""

    @abstractmethod
    def add_watch(
        self,
        usage_date: str,
        resource_id: str,
        video: dict,
        seconds: int,
        seen_at: str,
        max_rows: int = 5000,
    ) -> str:
        """Insert or extend today's last watch when the video id matches.

        Returns `inserted`, `updated`, `full`, or `skipped`.
        """

    @abstractmethod
    def get_watches(self, usage_date: str, resource_id: str) -> List[dict]:
        """YouTube/Shorts watch rows for that resource and date, in recorded order."""

    @abstractmethod
    def seed_watches(self, usage_date: str, resource_id: str, videos) -> None:
        """Copy legacy JSON videos into SQLite when that resource/date has no rows yet."""

    @abstractmethod
    def get_sessions_on_date(self, usage_date: str) -> List[SessionRecord]:
        """Foreground sessions whose start timestamp falls on that local date."""

    @abstractmethod
    def get_all_windows_for_date(self, usage_date: str) -> Dict[str, Dict[str, int]]:
        """Map resource_id → {window_id: seconds} for that date."""

    @abstractmethod
    def list_activity_dates(self) -> List[str]:
        """Distinct YYYY-MM-DD values that have usage, visits, watches, or sessions."""
