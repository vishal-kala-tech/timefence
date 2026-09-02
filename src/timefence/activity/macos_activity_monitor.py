import logging
import subprocess
from datetime import datetime

from ..models.activity import FrontmostApp, Observation
from .idle_detector import idle_seconds, is_screen_locked

LOCK_BUNDLE_IDS = {
    "com.apple.loginwindow",
    "com.apple.screensaver.engine",
}


def _looks_locked(frontmost):
    if frontmost is None or not frontmost.bundle_id:
        return False
    return frontmost.bundle_id.lower() in LOCK_BUNDLE_IDS


FRONTMOST_SCRIPT = """
tell application "System Events"
    try
        set p to first application process whose frontmost is true
        set appName to name of p
        set unixPid to unix id of p as text
        set bid to ""
        try
            set bid to bundle identifier of p
        end try
        return appName & tab & bid & tab & unixPid
    on error
        return ""
    end try
end tell
"""


def frontmost_application():
    """Return the macOS frontmost app (name, bundle ID, pid). Bundle ID is the canonical identifier."""
    for reader in (_frontmost_via_nsworkspace, _frontmost_via_applescript):
        try:
            app = reader()
        except Exception:
            logging.debug("Frontmost-app lookup failed", exc_info=True)
            continue
        if app is not None:
            return app
    return None


def _frontmost_via_nsworkspace():
    from AppKit import NSWorkspace

    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return None
    bundle_id = str(app.bundleIdentifier() or "").strip()
    name = str(app.localizedName() or "").strip()
    pid = int(app.processIdentifier())
    if not bundle_id and not name:
        return None
    return FrontmostApp(app_name=name, bundle_id=bundle_id, pid=pid)


def _frontmost_via_applescript():
    result = subprocess.run(
        ["osascript", "-e", FRONTMOST_SCRIPT],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    raw = (result.stdout or "").strip()
    if not raw:
        return None
    parts = raw.split("\t")
    name = parts[0].strip() if parts else ""
    bundle_id = parts[1].strip() if len(parts) > 1 else ""
    pid_text = parts[2].strip() if len(parts) > 2 else ""
    try:
        pid = int(pid_text)
    except (TypeError, ValueError):
        pid = 0
    if not name and not bundle_id:
        return None
    return FrontmostApp(app_name=name, bundle_id=bundle_id, pid=pid)


def running_bundle_ids():
    """Return {bundle_id.lower(): pid} for running GUI apps."""
    for reader in (_running_via_nsworkspace, _running_via_applescript):
        try:
            found = reader()
        except Exception:
            logging.debug("Running-apps lookup failed", exc_info=True)
            continue
        if found is not None:
            return found
    return {}


def _running_via_nsworkspace():
    from AppKit import NSWorkspace

    found = {}
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        bundle_id = str(app.bundleIdentifier() or "").strip()
        if not bundle_id:
            continue
        found[bundle_id.lower()] = int(app.processIdentifier())
    return found


RUNNING_SCRIPT = """
tell application "System Events"
    set out to ""
    repeat with p in application processes
        try
            set bid to bundle identifier of p
            if bid is not missing value and bid is not "" then
                set out to out & bid & tab & (unix id of p as text) & linefeed
            end if
        end try
    end repeat
    return out
end tell
"""


def _running_via_applescript():
    result = subprocess.run(
        ["osascript", "-e", RUNNING_SCRIPT],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    found = {}
    for line in (result.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        bundle_id = parts[0].strip()
        if not bundle_id:
            continue
        try:
            found[bundle_id.lower()] = int(parts[1].strip())
        except (TypeError, ValueError):
            found[bundle_id.lower()] = 0
    return found


def terminate_bundle_ids(bundle_ids):
    """Quit running apps whose bundle IDs match. Prefers NSRunningApplication, then AppleScript quit."""
    wanted = {str(item).strip().lower() for item in bundle_ids if str(item).strip()}
    if not wanted:
        return
    if _terminate_via_nsworkspace(wanted):
        return
    for bundle_id in wanted:
        try:
            subprocess.run(
                ["osascript", "-e", f'tell application id "{bundle_id}" to quit'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            continue


def _terminate_via_nsworkspace(wanted):
    try:
        from AppKit import NSWorkspace
    except Exception:
        return False
    matched = False
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        bundle_id = str(app.bundleIdentifier() or "").strip().lower()
        if bundle_id not in wanted:
            continue
        matched = True
        if not app.terminate():
            app.forceTerminate()
    return matched


class MacOSActivityMonitor:
    """Polls frontmost app, HID idle time, and lock state. Does not decide usage."""

    def __init__(self, frontmost_fn=None, idle_fn=None, locked_fn=None):
        self._frontmost_fn = frontmost_fn or frontmost_application
        self._idle_fn = idle_fn or idle_seconds
        self._locked_fn = locked_fn or is_screen_locked

    def capture(self, now=None):
        now = now or datetime.now()
        try:
            idle = float(self._idle_fn() or 0.0)
        except Exception:
            logging.debug("Idle-time lookup failed", exc_info=True)
            idle = 0.0
        try:
            locked = bool(self._locked_fn())
        except Exception:
            logging.debug("Lock-state lookup failed", exc_info=True)
            locked = False
        try:
            frontmost = self._frontmost_fn()
        except Exception:
            logging.exception("Frontmost application lookup failed")
            frontmost = None
        locked = locked or _looks_locked(frontmost)
        return Observation(
            timestamp=now,
            idle_seconds=idle,
            screen_locked=locked,
            frontmost=frontmost,
        )
