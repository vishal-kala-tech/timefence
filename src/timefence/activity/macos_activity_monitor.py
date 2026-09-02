"""Compatibility shim. Implementation lives in `timefence.platform.macos`."""

from ..platform.macos.activity_monitor import *  # noqa: F401,F403
from ..platform.macos.activity_monitor import MacOSActivityMonitor, frontmost_application, running_bundle_ids, terminate_bundle_ids

__all__ = [
    "MacOSActivityMonitor",
    "frontmost_application",
    "running_bundle_ids",
    "terminate_bundle_ids",
]
