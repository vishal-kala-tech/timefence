"""Linux stubs. Implement activity_monitor.py using the focused window + idle inhibitor APIs."""

from .activity_monitor import LinuxActivityMonitor, LinuxProcessController

__all__ = ["LinuxActivityMonitor", "LinuxProcessController"]
