"""Windows activity/process placeholders.

To implement:

- Frontmost: `GetForegroundWindow` + `GetWindowThreadProcessId` + process image
  name (or AppUserModelID). Store that string in `FrontmostApp.bundle_id` so
  matching can keep using `app_ids.win32` / `executables`.
- Idle: `GetLastInputInfo`.
- Lock: WTS session lock notifications, or a screensaver window class.
- Quit: `taskkill /PID` or WM_CLOSE.

Until then the agent runs but does not credit app screen-time on Windows.
"""

from ..base import UnsupportedActivityMonitor, UnsupportedProcessController
from ..detect import WINDOWS


class WindowsActivityMonitor(UnsupportedActivityMonitor):
    def __init__(self):
        super().__init__(WINDOWS)


class WindowsProcessController(UnsupportedProcessController):
    def __init__(self):
        super().__init__(WINDOWS)
