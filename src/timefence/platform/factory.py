"""Pick the ActivityMonitor / ProcessController for this OS."""

from .base import ActivityMonitor, ProcessController, UnsupportedActivityMonitor, UnsupportedProcessController
from .detect import DARWIN, LINUX, WINDOWS, current_os


def create_activity_monitor(os_name=None) -> ActivityMonitor:
    """Return the monitor for `os_name` (or the current OS)."""
    name = current_os(os_name)
    if name == DARWIN:
        from .macos import MacOSActivityMonitor

        return MacOSActivityMonitor()
    if name == WINDOWS:
        from .windows import WindowsActivityMonitor

        return WindowsActivityMonitor()
    if name == LINUX:
        from .linux import LinuxActivityMonitor

        return LinuxActivityMonitor()
    return UnsupportedActivityMonitor(name)


def create_process_controller(os_name=None) -> ProcessController:
    name = current_os(os_name)
    if name == DARWIN:
        from .macos import MacOSProcessController

        return MacOSProcessController()
    if name == WINDOWS:
        from .windows import WindowsProcessController

        return WindowsProcessController()
    if name == LINUX:
        from .linux import LinuxProcessController

        return LinuxProcessController()
    return UnsupportedProcessController(name)


# Convenience for the generic app adapter: one shared controller per process.
_process_controller = None


def process_controller() -> ProcessController:
    global _process_controller
    if _process_controller is None:
        _process_controller = create_process_controller()
    return _process_controller


def frontmost_application():
    return process_controller().frontmost_application()


def running_app_ids():
    return process_controller().running_app_ids()


def terminate_app_ids(app_ids):
    return process_controller().terminate_app_ids(app_ids)


# Historical names used by the generic app adapter and tests.
running_bundle_ids = running_app_ids
terminate_bundle_ids = terminate_app_ids
