from unittest.mock import MagicMock

import json

import pytest

from timefence.resources import roblox, youtube

_real_fetch_oembed = youtube.fetch_oembed
_real_lookup_metadata = youtube.lookup_metadata


@pytest.fixture(autouse=True)
def no_youtube_network(monkeypatch):
    youtube._metadata_cache.clear()
    monkeypatch.setattr(youtube, "fetch_oembed", lambda _url: None)


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


def test_youtube_is_active_when_inspect_returns_url(monkeypatch):
    run = MagicMock(
        return_value=MagicMock(stdout="https://www.youtube.com/watch?v=dQw4w9WgXcQ\nNever Gonna Give You Up - YouTube\n")
    )
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
    run = MagicMock(
        return_value=MagicMock(stdout="https://www.youtube.com/shorts/xyz12345678\nA Short - YouTube\n")
    )
    monkeypatch.setattr(youtube.subprocess, "run", run)
    assert youtube.is_active(SHORTS) is True
    assert run.call_args.args[0] == ["osascript", "-e", youtube.inspect_script(SHORTS)]


def test_inspect_returns_parsed_video(monkeypatch):
    monkeypatch.setattr(
        youtube.subprocess,
        "run",
        MagicMock(
            return_value=MagicMock(
                stdout="https://youtu.be/dQw4w9WgXcQ?t=30\nNever Gonna Give You Up - YouTube\n"
            )
        ),
    )
    page = youtube.inspect({})
    assert page["video"] == {
        "id": "dQw4w9WgXcQ",
        "title": "Never Gonna Give You Up",
        "channel": "",
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    }


def test_inspect_fills_channel_from_youtube_api(monkeypatch):
    monkeypatch.setattr(
        youtube.subprocess,
        "run",
        MagicMock(
            return_value=MagicMock(stdout="https://www.youtube.com/watch?v=dQw4w9WgXcQ\nNever Gonna Give You Up - YouTube\n")
        ),
    )
    monkeypatch.setattr(
        youtube,
        "lookup_metadata",
        lambda video_id: (
            {"title": "Never Gonna Give You Up", "channel": "Rick Astley"}
            if video_id == "dQw4w9WgXcQ"
            else None
        ),
    )
    page = youtube.inspect({})
    assert page["video"]["channel"] == "Rick Astley"
    assert page["channel"] == "Rick Astley"


def test_parse_video_from_watch_share_and_shorts_urls():
    assert youtube.parse_video("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLxx")["id"] == "dQw4w9WgXcQ"
    assert youtube.parse_video("https://m.youtube.com/watch?v=dQw4w9WgXcQ")["id"] == "dQw4w9WgXcQ"
    assert youtube.parse_video("https://youtu.be/dQw4w9WgXcQ")["url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    shorts = youtube.parse_video("https://www.youtube.com/shorts/xyz12345678", "Clip - YouTube", "Clip Channel")
    assert shorts == {
        "id": "xyz12345678",
        "title": "Clip",
        "channel": "Clip Channel",
        "url": "https://www.youtube.com/shorts/xyz12345678",
    }
    assert youtube.parse_video("https://www.youtube.com/") is None
    assert youtube.parse_video("https://www.youtube.com/watch?v=") is None


def test_inspect_script_does_not_scrape_the_page():
    script = youtube.inspect_script({})
    assert "execute javascript" not in script
    assert "ytInitialPlayerResponse" not in script


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def test_fetch_oembed_uses_author_name(monkeypatch):
    monkeypatch.setattr(youtube, "fetch_oembed", _real_fetch_oembed)
    monkeypatch.setattr(
        youtube,
        "urlopen",
        lambda _request, timeout=2: _FakeResponse({"title": "Song", "author_name": "Rick Astley"}),
    )
    meta = youtube.fetch_oembed("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert meta["channel"] == "Rick Astley"
    assert meta["title"] == "Song"


def test_lookup_metadata_uses_oembed(monkeypatch):
    monkeypatch.setattr(youtube, "lookup_metadata", _real_lookup_metadata)
    monkeypatch.setattr(
        youtube,
        "fetch_oembed",
        lambda url: {"title": "Song", "channel": "Rick Astley"} if "dQw4w9WgXcQ" in url else None,
    )
    meta = youtube.lookup_metadata("dQw4w9WgXcQ")
    assert meta["channel"] == "Rick Astley"


def test_lookup_metadata_reuses_cached_video(monkeypatch):
    monkeypatch.setattr(youtube, "lookup_metadata", _real_lookup_metadata)
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return {"title": "Song", "channel": "Rick Astley"}

    monkeypatch.setattr(youtube, "fetch_oembed", fake_fetch)
    first = youtube.lookup_metadata("dQw4w9WgXcQ")
    second = youtube.lookup_metadata("dQw4w9WgXcQ")
    assert first == second
    assert first["channel"] == "Rick Astley"
    assert len(calls) == 1


def test_lookup_metadata_evicts_oldest_when_full(monkeypatch):
    monkeypatch.setattr(youtube, "lookup_metadata", _real_lookup_metadata)
    calls = []

    def fake_fetch(url):
        calls.append(url)
        video_id = url.rsplit("v=", 1)[-1]
        return {"title": video_id, "channel": "Ch"}

    monkeypatch.setattr(youtube, "fetch_oembed", fake_fetch)
    size = youtube.METADATA_CACHE_SIZE
    ids = [f"video{i:02d}aaaaaa" for i in range(size + 1)]
    for video_id in ids:
        youtube.lookup_metadata(video_id)

    assert len(calls) == size + 1
    youtube.lookup_metadata(ids[1])
    assert len(calls) == size + 1
    youtube.lookup_metadata(ids[0])
    assert len(calls) == size + 2


def test_lookup_metadata_retries_failed_fetch(monkeypatch):
    monkeypatch.setattr(youtube, "lookup_metadata", _real_lookup_metadata)
    results = [None, {"title": "Song", "channel": "Rick Astley"}]
    monkeypatch.setattr(youtube, "fetch_oembed", lambda _url: results.pop(0))
    assert youtube.lookup_metadata("dQw4w9WgXcQ") is None
    assert youtube.lookup_metadata("dQw4w9WgXcQ")["channel"] == "Rick Astley"
