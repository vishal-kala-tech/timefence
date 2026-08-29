from unittest.mock import MagicMock

from timefence.notifications import show_notification


def test_show_notification_runs_osascript(monkeypatch):
    run = MagicMock(return_value=MagicMock(returncode=0, stderr="", stdout=""))
    monkeypatch.setattr("timefence.notifications.subprocess.run", run)

    assert show_notification("TimeFence", 'Roblox has 5 minutes remaining.') is True
    script = run.call_args.args[0][2]
    assert 'display notification "Roblox has 5 minutes remaining."' in script
    assert 'with title "TimeFence"' in script


def test_show_notification_escapes_quotes(monkeypatch):
    run = MagicMock(return_value=MagicMock(returncode=0, stderr="", stdout=""))
    monkeypatch.setattr("timefence.notifications.subprocess.run", run)

    show_notification('Say "hi"', 'He said "bye"')
    script = run.call_args.args[0][2]
    assert '\\"hi\\"' in script
    assert '\\"bye\\"' in script


def test_show_notification_failure_returns_false(monkeypatch):
    monkeypatch.setattr(
        "timefence.notifications.subprocess.run",
        MagicMock(side_effect=OSError("osascript missing")),
    )
    assert show_notification("TimeFence", "hello") is False
