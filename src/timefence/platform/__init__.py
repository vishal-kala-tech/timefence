"""OS adapters for frontmost-app capture and process control.

Production code should call `create_activity_monitor()` rather than
constructing `MacOSActivityMonitor` so Windows/Linux can plug in later.
"""

from .base import ActivityMonitor, ProcessController, UnsupportedActivityMonitor, UnsupportedProcessController
from .detect import current_os, os_aliases
from .factory import (
    create_activity_monitor,
    create_process_controller,
    frontmost_application,
    process_controller,
    running_app_ids,
    running_bundle_ids,
    terminate_app_ids,
    terminate_bundle_ids,
)

__all__ = [
    "ActivityMonitor",
    "ProcessController",
    "UnsupportedActivityMonitor",
    "UnsupportedProcessController",
    "create_activity_monitor",
    "create_process_controller",
    "current_os",
    "frontmost_application",
    "os_aliases",
    "process_controller",
    "running_app_ids",
    "running_bundle_ids",
    "terminate_app_ids",
    "terminate_bundle_ids",
]
