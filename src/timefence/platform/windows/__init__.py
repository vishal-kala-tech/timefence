"""Windows stubs. Implement activity_monitor.py using Win32 foreground HWND + GetLastInputInfo."""

from .activity_monitor import WindowsActivityMonitor, WindowsProcessController

__all__ = ["WindowsActivityMonitor", "WindowsProcessController"]
