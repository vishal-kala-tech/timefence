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
