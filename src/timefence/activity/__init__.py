"""Screen-time activity capture: frontmost app, HID idle, resource matching.

`create_activity_monitor()` picks the OS implementation. Matching is
configuration-driven (`bundle_ids` / `app_ids` / `url_contains`); do not
hard-code app names or browsers here.
"""

from ..platform import create_activity_monitor, current_os
from ..platform.macos import MacOSActivityMonitor, frontmost_application, running_bundle_ids, terminate_bundle_ids
from .idle_detector import idle_seconds, is_idle, is_screen_locked
from .matching import (
    app_ids_for,
    bundle_ids_for,
    find_resource_by_app_id,
    find_resource_by_bundle_id,
    find_resource_by_url,
    find_resource_for_activity,
    uses_app_capture,
)

__all__ = [
    "MacOSActivityMonitor",
    "app_ids_for",
    "bundle_ids_for",
    "create_activity_monitor",
    "current_os",
    "find_resource_by_app_id",
    "find_resource_by_bundle_id",
    "find_resource_by_url",
    "find_resource_for_activity",
    "frontmost_application",
    "idle_seconds",
    "is_idle",
    "is_screen_locked",
    "running_bundle_ids",
    "terminate_bundle_ids",
    "uses_app_capture",
]
