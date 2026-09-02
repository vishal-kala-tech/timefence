"""Screen-time activity capture: frontmost app, HID idle, resource matching.

MacOSActivityMonitor.capture() produces an Observation. UsageTracker.apply()
turns that into sessions and seconds. Matching is configuration-driven
(bundle_ids / url_contains); do not hard-code app names here.
"""

from .idle_detector import idle_seconds, is_idle, is_screen_locked
from .macos_activity_monitor import MacOSActivityMonitor, frontmost_application, running_bundle_ids, terminate_bundle_ids
from .matching import (
    bundle_ids_for,
    find_resource_by_bundle_id,
    find_resource_by_url,
    find_resource_for_activity,
    uses_app_capture,
)

__all__ = [
    "MacOSActivityMonitor",
    "bundle_ids_for",
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
