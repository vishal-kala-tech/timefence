import logging
import subprocess


def _applescript_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def show_notification(title: str, message: str) -> bool:
    script = (
        f"display notification {_applescript_string(message)} "
        f"with title {_applescript_string(title)}"
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        logging.exception("Notification failed")
        return False

    if result.returncode != 0:
        logging.warning("Notification failed: %s", (result.stderr or result.stdout).strip())
        return False
    return True
