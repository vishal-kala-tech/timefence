import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path

BLOCK_COUNTDOWN_SECONDS = 6
OPEN = "/usr/bin/open"
OSASCRIPT = "/usr/bin/osascript"


def _ping():
    try:
        subprocess.Popen(
            ["afplay", "/System/Library/Sounds/Ping.aiff"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _applescript_string(value: str) -> str:
    parts = str(value).split("\n")
    quoted = []
    for part in parts:
        quoted.append('"' + part.replace("\\", "\\\\").replace('"', '\\"') + '"')
    return " & return & ".join(quoted)


def overlay_script(title: str, message: str, seconds: int = BLOCK_COUNTDOWN_SECONDS) -> str:
    """Static System Events dialog used only if the countdown helper app fails."""
    seconds = max(1, int(seconds))
    body = f"{message}\n\nThis closes in {seconds} seconds."
    return (
        'tell application "System Events"\n'
        f"    display dialog {_applescript_string(body)} with title {_applescript_string(title)} "
        f'buttons {{"OK"}} default button "OK" giving up after {seconds}\n'
        "end tell\n"
    )


block_countdown_script = overlay_script


def _notifier_app():
    home = Path(
        os.environ.get(
            "TIME_FENCE_HOME",
            Path.home() / "Library/Application Support/TimeFence",
        )
    )
    app = home / "TimeFenceNotifier.app"
    macos = app / "Contents/MacOS"
    if not macos.is_dir():
        return None
    if (macos / "TimeFenceNotifier").exists() or (macos / "applet").exists():
        return app
    return None


def _payload_file(title: str, message: str, seconds: int) -> Path:
    folder = Path(tempfile.mkdtemp(prefix="timefence-notify-"))
    path = folder / "payload.json"
    path.write_text(
        json.dumps({"title": title, "message": message, "seconds": seconds}),
        encoding="utf-8",
    )
    return path


def _run_notifier_app(app: Path, title: str, message: str, seconds: int, *, wait: bool) -> bool:
    payload = _payload_file(title, message, seconds)
    cmd = [OPEN]
    if wait:
        cmd.append("-W")
    cmd.extend(["-n", "-a", str(app), "--args", str(payload)])
    logging.info("Showing countdown popup via %s", app)
    if wait:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=seconds + 8,
            check=False,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            logging.error(
                "Countdown helper failed: %s", err or f"open exit {result.returncode}"
            )
            return False
        return True
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return True


def _run_system_events_dialog(title: str, message: str, seconds: int, *, wait: bool) -> bool:
    script = overlay_script(title, message, seconds)
    logging.info("Showing static popup via System Events")
    if wait:
        result = subprocess.run(
            [OSASCRIPT, "-e", script],
            capture_output=True,
            text=True,
            timeout=seconds + 8,
            check=False,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            logging.error(
                "Popup failed: %s", err or f"osascript exit {result.returncode}"
            )
            return False
        return True

    proc = subprocess.Popen(
        [OSASCRIPT, "-e", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
        text=True,
    )
    try:
        proc.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        return True
    if proc.returncode == 0:
        return True
    err = (proc.stderr.read() if proc.stderr else "") or ""
    logging.error(
        "Popup failed: %s",
        err.strip() or f"osascript exit {proc.returncode}",
    )
    return False


def _run_overlay(title: str, message: str, seconds: int, *, wait: bool) -> bool:
    seconds = max(1, int(seconds))
    _ping()
    try:
        app = _notifier_app()
        if app is not None and _run_notifier_app(app, title, message, seconds, wait=wait):
            return True
        return _run_system_events_dialog(title, message, seconds, wait=wait)
    except Exception:
        logging.exception("Popup failed")
        return False


def show_notification(title: str, message: str, seconds: int = BLOCK_COUNTDOWN_SECONDS) -> bool:
    """Show the same 6-second countdown window as a block, without pausing the controller.

    Launched in the background so usage tracking and enforcement continue
    while the alert is on screen.
    """
    return _run_overlay(title, message, seconds, wait=False)


def show_block_countdown(title: str, message: str, seconds: int = BLOCK_COUNTDOWN_SECONDS) -> bool:
    """Show a 6-second countdown in one window, then return so the caller can enforce.

    Blocks the current thread until the countdown finishes. Failures are
    logged; the caller should still enforce.
    """
    return _run_overlay(title, message, seconds, wait=True)
