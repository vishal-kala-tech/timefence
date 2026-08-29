import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

from timefence.notifications import (
    block_countdown_script,
    overlay_script,
    show_block_countdown,
    show_notification,
)

HELPER = Path(__file__).resolve().parents[1] / "launchd" / "TimeFenceNotifier.py"


def test_countdown_helper_uses_tk_timer():
    source = HELPER.read_text(encoding="utf-8")
    assert "tkinter" in source
    assert "-topmost" in source
    assert "root.after" in source
    assert "display dialog" in source


def test_helper_load_payload_json(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("timefence_notifier", HELPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    payload = tmp_path / "payload.json"
    payload.write_text(
        json.dumps({"title": "TimeFence", "message": "YouTube is done.", "seconds": 4}),
        encoding="utf-8",
    )
    assert mod.load_payload([str(payload)]) == {
        "title": "TimeFence",
        "message": "YouTube is done.",
        "seconds": 4,
    }


def test_show_notification_uses_countdown_helper_when_installed(monkeypatch, tmp_path):
    app = tmp_path / "TimeFenceNotifier.app"
    popen = MagicMock()
    monkeypatch.setattr("timefence.notifications.subprocess.Popen", popen)
    monkeypatch.setattr("timefence.notifications.subprocess.run", MagicMock())
    monkeypatch.setattr("timefence.notifications._notifier_app", lambda: app)
    monkeypatch.setattr("timefence.notifications._ping", lambda: None)

    assert show_notification("TimeFence", "Roblox has 5 minutes remaining.") is True
    command = popen.call_args.args[0]
    assert command[0].endswith("open")
    assert "-W" not in command
    assert "-a" in command
    assert str(app) in command
    assert "--args" in command
    payload = Path(command[-1])
    assert payload.name == "payload.json"
    assert "Roblox has 5 minutes remaining." in payload.read_text(encoding="utf-8")


def test_show_notification_falls_back_to_system_events(monkeypatch):
    popen = MagicMock()
    popen.return_value.wait.side_effect = subprocess.TimeoutExpired(cmd="osascript", timeout=0.5)
    monkeypatch.setattr("timefence.notifications.subprocess.Popen", popen)
    monkeypatch.setattr("timefence.notifications._notifier_app", lambda: None)
    monkeypatch.setattr("timefence.notifications._ping", lambda: None)

    assert show_notification("TimeFence", "Roblox has 5 minutes remaining.") is True
    command = popen.call_args.args[0]
    assert command[0].endswith("osascript")
    script = command[2]
    assert "System Events" in script
    assert "display dialog" in script
    assert "Roblox has 5 minutes remaining." in script


def test_show_notification_escapes_quotes(monkeypatch):
    popen = MagicMock()
    popen.return_value.wait.side_effect = subprocess.TimeoutExpired(cmd="osascript", timeout=0.5)
    monkeypatch.setattr("timefence.notifications.subprocess.Popen", popen)
    monkeypatch.setattr("timefence.notifications._notifier_app", lambda: None)
    monkeypatch.setattr("timefence.notifications._ping", lambda: None)

    show_notification('Say "hi"', 'He said "bye"')
    script = popen.call_args.args[0][2]
    assert '"Say \\"hi\\""' in script
    assert '"He said \\"bye\\""' in script


def test_show_notification_failure_returns_false(monkeypatch):
    monkeypatch.setattr(
        "timefence.notifications.subprocess.Popen",
        MagicMock(side_effect=OSError("osascript missing")),
    )
    monkeypatch.setattr("timefence.notifications._notifier_app", lambda: None)
    monkeypatch.setattr("timefence.notifications._ping", lambda: None)
    assert show_notification("TimeFence", "hello") is False


def test_overlay_script_is_system_events_fallback():
    script = overlay_script("TimeFence", "Roblox has no time remaining today.")
    assert script == block_countdown_script("TimeFence", "Roblox has no time remaining today.")
    assert "System Events" in script
    assert "display dialog" in script
    assert "Roblox has no time remaining today." in script
    assert "giving up after 6" in script


def test_show_block_countdown_uses_helper_and_waits(monkeypatch, tmp_path):
    app = tmp_path / "TimeFenceNotifier.app"
    run = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr("timefence.notifications.subprocess.run", run)
    monkeypatch.setattr("timefence.notifications._notifier_app", lambda: app)
    monkeypatch.setattr("timefence.notifications._ping", lambda: None)

    assert show_block_countdown("TimeFence", "Closing YouTube.", seconds=6) is True
    run.assert_called_once()
    command = run.call_args.args[0]
    assert command[0].endswith("open")
    assert "-W" in command
    assert str(app) in command
    assert run.call_args.kwargs["timeout"] == 14


def test_show_block_countdown_falls_back_when_helper_fails(monkeypatch, tmp_path):
    app = tmp_path / "TimeFenceNotifier.app"
    run = MagicMock(
        side_effect=[
            MagicMock(returncode=1, stdout="", stderr="open failed"),
            MagicMock(returncode=0, stdout="", stderr=""),
        ]
    )
    monkeypatch.setattr("timefence.notifications.subprocess.run", run)
    monkeypatch.setattr("timefence.notifications._notifier_app", lambda: app)
    monkeypatch.setattr("timefence.notifications._ping", lambda: None)

    assert show_block_countdown("TimeFence", "hello") is True
    second = run.call_args_list[1].args[0]
    assert second[0].endswith("osascript")
    assert "display dialog" in second[2]


def test_show_block_countdown_nonzero_status_returns_false(monkeypatch):
    monkeypatch.setattr(
        "timefence.notifications.subprocess.run",
        MagicMock(return_value=MagicMock(returncode=1, stdout="", stderr="syntax error")),
    )
    monkeypatch.setattr("timefence.notifications._notifier_app", lambda: None)
    monkeypatch.setattr("timefence.notifications._ping", lambda: None)
    assert show_block_countdown("TimeFence", "hello") is False


def test_show_block_countdown_failure_returns_false(monkeypatch):
    monkeypatch.setattr(
        "timefence.notifications.subprocess.run",
        MagicMock(side_effect=OSError("osascript missing")),
    )
    monkeypatch.setattr("timefence.notifications._notifier_app", lambda: None)
    monkeypatch.setattr("timefence.notifications._ping", lambda: None)
    assert show_block_countdown("TimeFence", "hello") is False
