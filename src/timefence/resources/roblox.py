"""Legacy Roblox adapter: detect and quit by process name.

The shipped `roblox` resource is looked up by name in the controller, so this
module still runs inspect/enforce even when `bundle_ids` are set. Screen-time
does the counting (bundle ID). This file only answers running/frontmost and
`pkill`s the process pattern.

New apps should use `resources/app.py` (`type: app` + `bundle_ids`), not a
copy of this module. Process-name matching is locale-sensitive and collides.
"""

import subprocess

FRONTMOST_SCRIPT = (
    'tell application "System Events" to get name of first application process '
    "whose frontmost is true"
)


def _process_pattern(resource):
    return str((resource or {}).get("process_pattern") or "Roblox")


def _process_running(resource):
    result = subprocess.run(
        ["pgrep", "-f", _process_pattern(resource)],
        stdout=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _frontmost_name():
    result = subprocess.run(
        ["osascript", "-e", FRONTMOST_SCRIPT],
        capture_output=True,
        text=True,
    )
    return (result.stdout or "").strip()


def _is_frontmost(resource):
    name = _frontmost_name()
    pattern = _process_pattern(resource)
    return bool(name) and pattern.lower() in name.lower()


def inspect(resource):
    """None if Roblox is not running; otherwise whether it is frontmost."""
    if not _process_running(resource):
        return None
    return {"foreground": _is_frontmost(resource)}


def is_active(resource):
    page = inspect(resource)
    return bool(page and page.get("foreground"))


def enforce(resource):
    subprocess.run(
        ["pkill", "-9", "-f", _process_pattern(resource)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
