from unittest.mock import MagicMock

from timefence.resources import roblox, youtube


def test_roblox_is_active_when_pgrep_finds_process(monkeypatch):
    run = MagicMock(return_value=MagicMock(returncode=0))
    monkeypatch.setattr(roblox.subprocess, "run", run)

    assert roblox.is_active({"process_pattern": "RobloxPlayer"}) is True
    run.assert_called_once_with(
        ["pgrep", "-f", "RobloxPlayer"],
        stdout=roblox.subprocess.DEVNULL,
    )


def test_roblox_is_inactive_when_pgrep_misses(monkeypatch):
    monkeypatch.setattr(
        roblox.subprocess,
        "run",
        MagicMock(return_value=MagicMock(returncode=1)),
    )
    assert roblox.is_active({}) is False


def test_roblox_defaults_process_pattern(monkeypatch):
    run = MagicMock(return_value=MagicMock(returncode=1))
    monkeypatch.setattr(roblox.subprocess, "run", run)
    roblox.is_active({})
    assert run.call_args.args[0] == ["pgrep", "-f", "Roblox"]


def test_roblox_enforce_sends_kill(monkeypatch):
    run = MagicMock()
    monkeypatch.setattr(roblox.subprocess, "run", run)
    roblox.enforce({"process_pattern": "RobloxPlayer"})
    run.assert_called_once_with(
        ["pkill", "-9", "-f", "RobloxPlayer"],
        stdout=roblox.subprocess.DEVNULL,
        stderr=roblox.subprocess.DEVNULL,
    )


def test_youtube_is_active_only_on_yes(monkeypatch):
    run = MagicMock(return_value=MagicMock(stdout="YES\n"))
    monkeypatch.setattr(youtube.subprocess, "run", run)
    assert youtube.is_active({}) is True
    run.assert_called_once_with(
        ["osascript", "-e", youtube.ACTIVE_SCRIPT],
        capture_output=True,
        text=True,
    )


def test_youtube_is_inactive_on_no_or_empty(monkeypatch):
    monkeypatch.setattr(
        youtube.subprocess,
        "run",
        MagicMock(return_value=MagicMock(stdout="NO\n")),
    )
    assert youtube.is_active({}) is False

    monkeypatch.setattr(
        youtube.subprocess,
        "run",
        MagicMock(return_value=MagicMock(stdout="")),
    )
    assert youtube.is_active({}) is False


def test_youtube_enforce_closes_tabs(monkeypatch):
    run = MagicMock()
    monkeypatch.setattr(youtube.subprocess, "run", run)
    youtube.enforce({})
    run.assert_called_once_with(
        ["osascript", "-e", youtube.CLOSE_SCRIPT],
        stdout=youtube.subprocess.DEVNULL,
        stderr=youtube.subprocess.DEVNULL,
    )


def test_youtube_scripts_match_youtube_and_short_links():
    assert "youtube.com/" in youtube.ACTIVE_SCRIPT
    assert "youtu.be/" in youtube.ACTIVE_SCRIPT
    assert "youtube.com/" in youtube.CLOSE_SCRIPT
    assert "youtu.be/" in youtube.CLOSE_SCRIPT


WATCH = {
    "url_contains": ["youtube.com/watch", "youtu.be/"],
    "url_excludes": ["youtube.com/shorts"],
}
SHORTS = {"url_contains": ["youtube.com/shorts"]}


def test_url_matches_separates_watch_from_shorts():
    watch = "https://www.youtube.com/watch?v=abc"
    shorts = "https://www.youtube.com/shorts/xyz"
    share = "https://youtu.be/abc"
    home = "https://www.youtube.com/"

    assert youtube.url_matches(watch, WATCH)
    assert youtube.url_matches(share, WATCH)
    assert not youtube.url_matches(shorts, WATCH)
    assert not youtube.url_matches(home, WATCH)

    assert youtube.url_matches(shorts, SHORTS)
    assert youtube.url_matches("https://m.youtube.com/shorts/xyz", SHORTS)
    assert not youtube.url_matches(watch, SHORTS)
    assert not youtube.url_matches(share, SHORTS)
    assert not youtube.url_matches(home, SHORTS)


def test_active_and_close_scripts_use_resource_url_patterns():
    watch_script = youtube.active_script(WATCH)
    shorts_script = youtube.close_script(SHORTS)
    assert "youtube.com/watch" in watch_script
    assert "youtu.be/" in watch_script
    assert "youtube.com/shorts" in watch_script
    assert "youtube.com/shorts" in shorts_script
    assert "youtube.com/watch" not in shorts_script


def test_youtube_is_active_uses_generated_script(monkeypatch):
    run = MagicMock(return_value=MagicMock(stdout="YES\n"))
    monkeypatch.setattr(youtube.subprocess, "run", run)
    assert youtube.is_active(SHORTS) is True
    assert run.call_args.args[0] == ["osascript", "-e", youtube.active_script(SHORTS)]
