"""HID idle time for macOS.

UsageTracker treats the user as idle when `idle_seconds >= idle_threshold_seconds`
(default 120). Idle time does not consume screen-time budget, and an open
session is closed.

We call CoreGraphics directly via ctypes instead of `import Quartz` (PyObjC).
PyObjC can hang for a long time in launchd/sandbox when talking to the window
server. ctypes `CGEventSourceSecondsSinceLastEventType` is enough.

HIDSystemState (1) is the keyboard/mouse idle clock, not the combined session
state. kCGAnyInputEventType is (CGEventType)~0, i.e. any input.

If both backends fail, idle_seconds() returns 0: we count time rather than
pretend the user has been idle forever.
"""

import ctypes
import ctypes.util
import subprocess

# CGEventSourceStateID / CGEventType from CGEventTypes.h
kCGEventSourceStateHIDSystemState = 1
kCGAnyInputEventType = 0xFFFFFFFF


def idle_seconds():
    """Return seconds since the last HID keyboard/mouse event."""
    for reader in (_idle_via_ctypes, _idle_via_ioreg):
        try:
            value = reader()
        except Exception:
            continue
        if value is None:
            continue
        return max(0.0, float(value))
    return 0.0


def _idle_via_ctypes():
    path = ctypes.util.find_library("ApplicationServices") or ctypes.util.find_library("CoreGraphics")
    if not path:
        raise RuntimeError("CoreGraphics library not found")
    lib = ctypes.cdll.LoadLibrary(path)
    lib.CGEventSourceSecondsSinceLastEventType.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    lib.CGEventSourceSecondsSinceLastEventType.restype = ctypes.c_double
    return lib.CGEventSourceSecondsSinceLastEventType(
        kCGEventSourceStateHIDSystemState,
        kCGAnyInputEventType,
    )


def _idle_via_ioreg():
    # HIDIdleTime is nanoseconds since last HID event on IOHIDSystem.
    result = subprocess.run(
        ["ioreg", "-c", "IOHIDSystem", "-d", "4"],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    for line in result.stdout.splitlines():
        if "HIDIdleTime" not in line:
            continue
        raw = line.split("=")[-1].strip()
        return int(raw) / 1_000_000_000
    raise RuntimeError("HIDIdleTime not found")


def is_idle(threshold_seconds, seconds=None):
    """True when idle time is at or above the configured threshold.

    Pass `seconds` in tests to avoid calling the real HID API.
    """
    if threshold_seconds is None:
        return False
    threshold = float(threshold_seconds)
    if threshold < 0:
        return False
    value = idle_seconds() if seconds is None else float(seconds)
    return value >= threshold


def is_screen_locked():
    """Hook for a dedicated lock API. Currently unused (always False).

    MacOSActivityMonitor already treats loginwindow/screensaver as locked via
    the frontmost bundle ID. Lid-close/sleep is caught by UsageTracker when
    elapsed time exceeds max_countable_interval_seconds. Tests inject locked_fn
    to simulate lock without waiting for those signals.
    """
    return False
