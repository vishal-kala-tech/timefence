import ctypes
import ctypes.util
import subprocess

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
    if threshold_seconds is None:
        return False
    threshold = float(threshold_seconds)
    if threshold < 0:
        return False
    value = idle_seconds() if seconds is None else float(seconds)
    return value >= threshold


def is_screen_locked():
    """Optional extra lock check. Default is False; the monitor also treats loginwindow as locked."""
    return False
