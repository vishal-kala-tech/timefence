"""Print one live snapshot as JSON.

Run from the project tree:

    PYTHONPATH=src python -m timefence.activity

Use this to confirm a Mac app's bundle ID before adding it to rules.json.
"""

from datetime import datetime
import json

from .idle_detector import idle_seconds, is_screen_locked
from .macos_activity_monitor import frontmost_application


def main():
    payload = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "idle_seconds": None,
        "screen_locked": None,
        "app": None,
    }
    try:
        payload["idle_seconds"] = round(float(idle_seconds()), 1)
    except Exception as exc:
        payload["idle_error"] = str(exc)
    try:
        payload["screen_locked"] = bool(is_screen_locked())
    except Exception as exc:
        payload["lock_error"] = str(exc)
    try:
        front = frontmost_application()
        payload["app"] = front.to_dict() if front else None
    except Exception as exc:
        payload["app_error"] = str(exc)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
