from unittest.mock import MagicMock

from timefence.notifications import show_notification


def test_show_notification_uses_dialog_without_auto_dismiss(monkeypatch):
    popen = MagicMock()
    monkeypatch.setattr("timefence.notifications.subprocess.Popen", popen)

    assert show_notification("TimeFence", "Roblox has 5 minutes remaining.") is True
    command = popen.call_args.args[0]
    assert command[:2] == ["osascript", "-e"]
    script = command[2]
    assert "display dialog" in script
    assert 'with title "TimeFence"' in script
    assert "Roblox has 5 minutes remaining." in script
    assert "giving up after" not in script


def test_show_notification_escapes_quotes(monkeypatch):
    popen = MagicMock()
    monkeypatch.setattr("timefence.notifications.subprocess.Popen", popen)

    show_notification('Say "hi"', 'He said "bye"')
    script = popen.call_args.args[0][2]
    assert '\\"hi\\"' in script
    assert '\\"bye\\"' in script


def test_show_notification_failure_returns_false(monkeypatch):
    monkeypatch.setattr(
        "timefence.notifications.subprocess.Popen",
        MagicMock(side_effect=OSError("osascript missing")),
    )
    assert show_notification("TimeFence", "hello") is False
