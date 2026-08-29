from unittest.mock import MagicMock

from timefence.notifications import (
    block_countdown_script,
    overlay_script,
    show_block_countdown,
    show_notification,
)


def test_show_notification_uses_countdown_window(monkeypatch):
    popen = MagicMock()
    monkeypatch.setattr("timefence.notifications.subprocess.Popen", popen)

    assert show_notification("TimeFence", "Roblox has 5 minutes remaining.") is True
    command = popen.call_args.args[0]
    assert command == ["osascript", "-l", "JavaScript"]
    script = popen.return_value.stdin.write.call_args.args[0]
    assert "NSWindow" in script
    assert "stringValue" in script
    assert "Roblox has 5 minutes remaining." in script
    assert "NSButton" not in script
    assert "display dialog" not in script
    popen.return_value.stdin.close.assert_called_once()


def test_show_notification_escapes_quotes(monkeypatch):
    popen = MagicMock()
    monkeypatch.setattr("timefence.notifications.subprocess.Popen", popen)

    show_notification('Say "hi"', 'He said "bye"')
    script = popen.return_value.stdin.write.call_args.args[0]
    assert '"Say \\"hi\\""' in script
    assert '"He said \\"bye\\""' in script


def test_show_notification_failure_returns_false(monkeypatch):
    monkeypatch.setattr(
        "timefence.notifications.subprocess.Popen",
        MagicMock(side_effect=OSError("osascript missing")),
    )
    assert show_notification("TimeFence", "hello") is False


def test_overlay_script_is_one_window_with_live_timer():
    script = overlay_script("TimeFence", "Roblox has no time remaining today.")
    assert script == block_countdown_script("TimeFence", "Roblox has no time remaining today.")
    assert "ObjC.import" in script
    assert '"TimeFence"' in script
    assert "Roblox has no time remaining today." in script
    assert "NSWindow" in script
    assert "stringValue" in script
    assert "NSButton" not in script
    assert "display dialog" not in script


def test_show_block_countdown_runs_osascript_and_waits(monkeypatch):
    run = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr("timefence.notifications.subprocess.run", run)
    monkeypatch.setattr("timefence.notifications._ping", lambda: None)

    assert show_block_countdown("TimeFence", "Closing YouTube.", seconds=6) is True
    run.assert_called_once()
    assert run.call_args.args[0] == ["osascript", "-l", "JavaScript"]
    script = run.call_args.kwargs["input"]
    assert "NSWindow" in script
    assert "stringValue" in script
    assert "NSButton" not in script
    assert "display dialog" not in script
    assert run.call_args.kwargs["timeout"] == 14


def test_show_block_countdown_nonzero_status_returns_false(monkeypatch):
    monkeypatch.setattr(
        "timefence.notifications.subprocess.run",
        MagicMock(return_value=MagicMock(returncode=1, stdout="", stderr="syntax error")),
    )
    monkeypatch.setattr("timefence.notifications._ping", lambda: None)
    assert show_block_countdown("TimeFence", "hello") is False


def test_show_block_countdown_failure_returns_false(monkeypatch):
    monkeypatch.setattr(
        "timefence.notifications.subprocess.run",
        MagicMock(side_effect=OSError("osascript missing")),
    )
    monkeypatch.setattr("timefence.notifications._ping", lambda: None)
    assert show_block_countdown("TimeFence", "hello") is False
