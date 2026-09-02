"""Generic app: inspect/enforce by OS app id (`bundle_ids` on macOS).

Used when the resource `type` is `app` (Cursor, Chrome, VS Code, …). Counting
is done by the screen-time monitor; this module only answers "is it running /
frontmost?" and quits it.

Process lookup/quit goes through `platform.process_controller()` so Windows
and Linux can replace pgrep/pkill later. `process_pattern` remains a Unix
fallback.
"""

import subprocess

from ..activity.matching import app_ids_for
from ..platform import frontmost_application, running_app_ids, terminate_app_ids


def _process_pattern(resource):
    return str((resource or {}).get("process_pattern") or "").strip()


def _bundle_ids(resource):
    return app_ids_for(resource)


def _process_running(resource):
    pattern = _process_pattern(resource)
    if not pattern:
        return False
    result = subprocess.run(
        ["pgrep", "-f", pattern],
        stdout=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _bundle_running(resource):
    wanted = {item.lower() for item in _bundle_ids(resource)}
    if not wanted:
        return False
    running = running_app_ids()
    return any(bundle_id in running for bundle_id in wanted)


def is_running(resource):
    return _process_running(resource) or _bundle_running(resource)


def inspect(resource):
    """None if the app is not running; otherwise whether it is the frontmost app (by bundle ID).

    `foreground` False means the process is up in the background. Screen-time
    does not count that; enforcement may still quit it when the budget is gone.
    """
    if not is_running(resource):
        return None
    front = frontmost_application()
    wanted = {item.lower() for item in _bundle_ids(resource)}
    bundle_id = (front.bundle_id or "").lower() if front else ""
    foreground = bool(bundle_id and bundle_id in wanted)
    payload = {"foreground": foreground}
    if front:
        payload.update(front.to_dict())
    return payload


def is_active(resource):
    page = inspect(resource)
    return bool(page and page.get("foreground"))


def enforce(resource):
    """Quit matching bundle IDs first, then pkill the optional process pattern."""
    ids = _bundle_ids(resource)
    if ids:
        terminate_app_ids(ids)
    pattern = _process_pattern(resource)
    if pattern:
        subprocess.run(
            ["pkill", "-9", "-f", pattern],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
