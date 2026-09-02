"""OS-independent activity and process control.

Add a new OS by implementing `ActivityMonitor` + `ProcessController` under
`platform/<os>/` and registering them in `platform/factory.py`. The controller
and UsageTracker never import AppKit, Win32, or X11 directly.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Optional

from ..models.activity import FrontmostApp, Observation


class ActivityMonitor(ABC):
    """One poll of (time, idle, lock, frontmost app). Does not match resources or add seconds."""

    @abstractmethod
    def capture(self, now=None) -> Observation:
        """Return an Observation for `now`. Must not raise; degrade to empty frontmost / idle 0."""


class ProcessController(ABC):
    """Running-app lookup and quit. Used by the generic app adapter for enforcement."""

    @abstractmethod
    def frontmost_application(self) -> Optional[FrontmostApp]:
        pass

    @abstractmethod
    def running_app_ids(self) -> Dict[str, int]:
        """Map lowercased app id → pid. On macOS the id is a bundle ID."""

    @abstractmethod
    def terminate_app_ids(self, app_ids) -> None:
        """Quit running apps whose ids match. Missing processes are ignored."""


class UnsupportedActivityMonitor(ActivityMonitor):
    """Placeholder so the agent still runs on an OS we have not implemented yet.

    Returns an empty snapshot (no frontmost app, not idle, not locked). App
    screen-time will not accumulate until a real monitor is added. Logs once.
    """

    def __init__(self, os_name: str):
        self.os_name = os_name
        self._warned = False

    def capture(self, now=None) -> Observation:
        if not self._warned:
            import logging

            logging.warning(
                "Activity capture is not implemented on %s yet. "
                "Add platform/%s/activity_monitor.py. See docs/design.md.",
                self.os_name,
                _package_name(self.os_name),
            )
            self._warned = True
        return Observation(
            timestamp=now or datetime.now(),
            idle_seconds=0.0,
            screen_locked=False,
            frontmost=None,
        )


class UnsupportedProcessController(ProcessController):
    def __init__(self, os_name: str):
        self.os_name = os_name

    def frontmost_application(self):
        return None

    def running_app_ids(self):
        return {}

    def terminate_app_ids(self, app_ids):
        import logging

        logging.debug("Process terminate is not implemented on %s", self.os_name)


def _package_name(os_name):
    if os_name == "darwin":
        return "macos"
    if os_name == "win32":
        return "windows"
    return os_name or "unknown"
