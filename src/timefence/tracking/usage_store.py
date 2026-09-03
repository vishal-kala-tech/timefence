from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple

from ..models.usage import DailyUsage, SessionRecord

ResourceWindows = Dict[Tuple[str, str], Dict[str, int]]


class UsageStore(ABC):
    """Persistence for screen-time totals and sessions.

    Every usage row is keyed by (resource_type, resource_id). App rows are
    physical foreground time (screen time). Website and video_category rows
    attribute that same time; they must not be summed into screen time.
    """

    @abstractmethod
    def ensure_resource(
        self,
        resource_type: str,
        resource_id: str,
        display_name: str = "",
        identifier_type: str = "",
        metadata_json: Optional[str] = None,
        updated_at: str = "",
    ) -> dict:
        """Insert the resource if missing; refresh name/metadata; keep created_at."""

    @abstractmethod
    def get_resource(self, resource_type: str, resource_id: str) -> Optional[dict]:
        pass

    @abstractmethod
    def list_resources(self, resource_type: Optional[str] = None) -> List[dict]:
        pass

    @abstractmethod
    def add_active_seconds(
        self,
        usage_date: str,
        resource_type: str,
        resource_id: str,
        seconds: int,
        updated_at: str,
    ) -> int:
        """Atomically add seconds to the day's total. Returns the new total."""

    @abstractmethod
    def get_daily(self, usage_date: str, resource_type: str, resource_id: str) -> Optional[DailyUsage]:
        pass

    @abstractmethod
    def get_all_daily(self, usage_date: str, resource_type: Optional[str] = None) -> List[DailyUsage]:
        pass

    @abstractmethod
    def add_window_seconds(
        self,
        usage_date: str,
        resource_type: str,
        resource_id: str,
        window_id: str,
        seconds: int,
        updated_at: str,
    ) -> int:
        """Atomically add seconds to a day's window total. Returns the new window total."""

    @abstractmethod
    def get_windows(self, usage_date: str, resource_type: str, resource_id: str) -> Dict[str, int]:
        """Map window_id → usage_seconds for that resource and date."""

    @abstractmethod
    def start_session(
        self,
        resource_type: str,
        resource_id: str,
        started_at: str,
        pid: Optional[int] = None,
        identifier: str = "",
        created_at: str = "",
    ) -> int:
        pass

    @abstractmethod
    def update_session(self, session_id: int, duration_seconds: int, ended_at: Optional[str] = None) -> None:
        pass

    @abstractmethod
    def end_session(self, session_id: int, ended_at: str, duration_seconds: int) -> None:
        pass

    @abstractmethod
    def get_open_session(self, resource_type: str, resource_id: str) -> Optional[SessionRecord]:
        pass

    @abstractmethod
    def get_open_sessions(self) -> List[SessionRecord]:
        pass

    @abstractmethod
    def record_warning(
        self,
        usage_date: str,
        resource_type: str,
        resource_id: str,
        warning_key: str,
        triggered_at: str = "",
    ) -> bool:
        """Persist a per-day warning key. Returns True if this is the first time it was recorded."""

    @abstractmethod
    def has_warning(self, usage_date: str, resource_type: str, resource_id: str, warning_key: str) -> bool:
        pass

    @abstractmethod
    def add_browse_visit(
        self,
        usage_date: str,
        resource_id: str,
        host: str,
        url: str,
        title: str,
        seconds: int,
        seen_at: str,
        browser_resource_id: str = "",
        browser_name: str = "",
        resource_type: str = "website",
        max_rows: int = 5000,
    ) -> str:
        """Insert or extend today's last visit when the URL matches.

        Returns `inserted`, `updated`, `full`, or `skipped`.
        """

    @abstractmethod
    def get_browse_visits(self, usage_date: str) -> List[dict]:
        """Front-tab visits for that date, in the order they were recorded."""

    @abstractmethod
    def add_watch(
        self,
        usage_date: str,
        resource_id: str,
        video: dict,
        seconds: int,
        seen_at: str,
        resource_type: str = "video_category",
        platform: str = "youtube",
        max_rows: int = 5000,
    ) -> str:
        """Insert or extend today's last watch when the video id matches.

        Returns `inserted`, `updated`, `full`, or `skipped`.
        """

    @abstractmethod
    def get_watches(
        self,
        usage_date: str,
        resource_id: str,
        resource_type: str = "video_category",
    ) -> List[dict]:
        """Watch rows for that video category and date, in recorded order."""

    @abstractmethod
    def get_sessions_on_date(self, usage_date: str) -> List[SessionRecord]:
        """Foreground sessions whose start timestamp falls on that local date."""

    @abstractmethod
    def get_all_windows_for_date(self, usage_date: str) -> ResourceWindows:
        """Map (resource_type, resource_id) → {window_id: seconds} for that date."""

    @abstractmethod
    def list_activity_dates(self) -> List[str]:
        """Distinct YYYY-MM-DD values that have usage, visits, watches, or sessions."""
