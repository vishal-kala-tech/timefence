#!/usr/bin/env python3
"""Countdown window for TimeFence. Launched as TimeFenceNotifier.app via open(1)."""

from __future__ import annotations

import json
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

LOG = Path.home() / "Library/Logs/TimeFence/notifier.log"


def log(message: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='seconds')} | {message}\n")
    except OSError:
        pass


def load_payload(argv: list[str]) -> dict | None:
    if not argv:
        return None
    raw = argv[0]
    path = Path(raw)
    if path.suffix.lower() == ".json" and path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        seconds = int(data.get("seconds") or 6)
        return {
            "title": str(data.get("title") or "TimeFence"),
            "message": str(data.get("message") or ""),
            "seconds": seconds if seconds >= 1 else 6,
        }
    if len(argv) >= 2:
        seconds = int(argv[2]) if len(argv) >= 3 else 6
        return {
            "title": str(argv[0]),
            "message": str(argv[1]),
            "seconds": seconds if seconds >= 1 else 6,
        }
    return None


def _applescript_string(value: str) -> str:
    parts = str(value).split("\n")
    quoted = []
    for part in parts:
        quoted.append('"' + part.replace("\\", "\\\\").replace('"', '\\"') + '"')
    return " & return & ".join(quoted)


def show_dialog(title: str, message: str, seconds: int) -> bool:
    body = f"{message}\n\nThis closes in {seconds} seconds."
    script = (
        'tell application "System Events"\n'
        f"    display dialog {_applescript_string(body)} with title {_applescript_string(title)} "
        f'buttons {{"OK"}} default button "OK" giving up after {seconds}\n'
        "end tell\n"
    )
    result = subprocess.run(
        ["/usr/bin/osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=seconds + 8,
        check=False,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        log(f"System Events dialog failed: {err or result.returncode}")
        return False
    return True


def show_countdown(title: str, message: str, seconds: int) -> None:
    import tkinter as tk

    root = tk.Tk()
    root.title(title)
    root.resizable(False, False)
    root.attributes("-topmost", True)
    try:
        root.attributes("-type", "utility")
    except tk.TclError:
        pass
    root.protocol("WM_DELETE_WINDOW", lambda: None)

    width, height = 480, 220
    root.update_idletasks()
    x = max(0, (root.winfo_screenwidth() - width) // 2)
    y = max(0, (root.winfo_screenheight() - height) // 3)
    root.geometry(f"{width}x{height}+{x}+{y}")

    wrap = tk.Label(
        root,
        text=message,
        font=("Helvetica", 16),
        wraplength=440,
        justify="center",
    )
    wrap.pack(padx=20, pady=(28, 8))
    timer = tk.Label(root, text=str(seconds), font=("Helvetica", 36, "bold"))
    timer.pack(pady=8)

    remaining = {"value": seconds}

    def tick():
        n = remaining["value"]
        if n <= 0:
            root.destroy()
            return
        timer.config(text=str(n))
        remaining["value"] = n - 1
        root.after(1000, tick)

    root.after(0, tick)
    root.lift()
    root.focus_force()
    root.mainloop()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    log(f"start argv={argv!r}")
    try:
        payload = load_payload(argv)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        log(f"invalid payload: {exc}")
        return 1
    if not payload:
        log("no payload")
        return 1
    try:
        show_countdown(payload["title"], payload["message"], payload["seconds"])
        log("tk countdown finished")
        return 0
    except Exception as exc:
        log(f"tk failed: {exc}")
        log(traceback.format_exc())
        if show_dialog(payload["title"], payload["message"], payload["seconds"]):
            log("fell back to System Events dialog")
            return 0
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
