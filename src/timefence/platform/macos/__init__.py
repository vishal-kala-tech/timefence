"""macOS frontmost-app, HID idle, and process control."""

from .activity_monitor import MacOSActivityMonitor, frontmost_application, running_bundle_ids, terminate_bundle_ids
from .idle import idle_seconds, is_idle, is_screen_locked
from .processes import MacOSProcessController

__all__ = [
    "MacOSActivityMonitor",
    "MacOSProcessController",
    "frontmost_application",
    "idle_seconds",
    "is_idle",
    "is_screen_locked",
    "running_bundle_ids",
    "terminate_bundle_ids",
]
