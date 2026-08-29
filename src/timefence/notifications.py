import logging
import subprocess


def _applescript_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ping():
    try:
        subprocess.Popen(
            ["afplay", "/System/Library/Sounds/Ping.aiff"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def show_notification(title: str, message: str) -> bool:
    """Show a dialog that stays until OK is clicked.

    The dialog is launched in the background so the controller can keep
    tracking usage and enforcing limits while the alert is on screen.
    """
    script = (
        f"display dialog {_applescript_string(message)} "
        f"with title {_applescript_string(title)} "
        'with icon caution '
        'buttons {"OK"} default button "OK"'
    )
    _ping()
    try:
        subprocess.Popen(
            ["osascript", "-e", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        logging.exception("Notification failed")
        return False
    return True
