"""Linux activity/process placeholders.

To implement:

- Frontmost: focused X11/Wayland window → .desktop id or executable.
  Put that string in `FrontmostApp.bundle_id`; match with `app_ids.linux`.
- Idle: Mutter/GNOME idle, xprintidle, or /proc.
- Lock: screensaver DBus (org.freedesktop.ScreenSaver).
- Quit: SIGTERM the PID, or `gtk-launch` inverse.

Until then the agent runs but does not credit app screen-time on Linux.
"""

from ..base import UnsupportedActivityMonitor, UnsupportedProcessController
from ..detect import LINUX


class LinuxActivityMonitor(UnsupportedActivityMonitor):
    def __init__(self):
        super().__init__(LINUX)


class LinuxProcessController(UnsupportedProcessController):
    def __init__(self):
        super().__init__(LINUX)
