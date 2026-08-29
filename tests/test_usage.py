import json
from datetime import date, datetime, timedelta
from unittest.mock import patch

from timefence.usage import add_usage, get_usage, load_state, note_video


def test_get_usage_returns_zero_when_file_missing(tmp_path):
    assert get_usage(tmp_path, "roblox") == 0
    assert get_usage(tmp_path, "roblox", window_id="after_school") == 0


def test_get_usage_reads_total_and_window_seconds(tmp_path):
    path = tmp_path / "roblox" / f"{date.today().isoformat()}.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps(
            {
                "date": date.today().isoformat(),
                "total_usage_seconds": 2100,
                "windows": {"after_school": {"usage_seconds": 1800}, "evening": {"usage_seconds": 300}},
            }
        )
    )
    assert get_usage(tmp_path, "roblox") == 2100
    assert get_usage(tmp_path, "roblox", window_id="after_school") == 1800
    assert get_usage(tmp_path, "roblox", window_id="evening") == 300
    assert get_usage(tmp_path, "roblox", window_id="missing") == 0


def test_get_usage_reads_legacy_usage_seconds_field(tmp_path):
    path = tmp_path / "roblox" / f"{date.today().isoformat()}.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"usage_seconds": 120}))
    assert get_usage(tmp_path, "roblox") == 120


def test_get_usage_defaults_missing_totals_to_zero(tmp_path):
    path = tmp_path / "roblox" / f"{date.today().isoformat()}.json"
    path.parent.mkdir()
    path.write_text(json.dumps({}))
    assert get_usage(tmp_path, "roblox") == 0


def test_get_usage_resets_invalid_json(tmp_path):
    path = tmp_path / "roblox" / f"{date.today().isoformat()}.json"
    path.parent.mkdir()
    path.write_text("not-json")
    assert get_usage(tmp_path, "roblox") == 0


def test_add_usage_creates_file_and_tracks_window(tmp_path):
    state = add_usage(tmp_path, "youtube", 15, window_id="evening")
    assert state["total_usage_seconds"] == 15
    assert state["windows"]["evening"]["usage_seconds"] == 15
    assert get_usage(tmp_path, "youtube") == 15
    path = tmp_path / "youtube" / f"{date.today().isoformat()}.json"
    payload = json.loads(path.read_text())
    assert payload["total_usage_seconds"] == 15
    assert payload["windows"]["evening"]["usage_seconds"] == 15
    assert not path.with_suffix(".tmp").exists()


def test_add_usage_accumulates_daily_and_per_window(tmp_path):
    add_usage(tmp_path, "roblox", 15, window_id="after_school")
    add_usage(tmp_path, "roblox", 10, window_id="evening")
    add_usage(tmp_path, "roblox", 5, window_id="after_school")
    assert get_usage(tmp_path, "roblox") == 30
    assert get_usage(tmp_path, "roblox", window_id="after_school") == 20
    assert get_usage(tmp_path, "roblox", window_id="evening") == 10


def test_usage_is_isolated_per_resource(tmp_path):
    add_usage(tmp_path, "roblox", 10, window_id="after_school")
    add_usage(tmp_path, "youtube", 20, window_id="evening")
    assert get_usage(tmp_path, "roblox") == 10
    assert get_usage(tmp_path, "youtube") == 20


def test_usage_resets_on_a_new_day(tmp_path):
    today = date(2024, 1, 15)
    yesterday = today - timedelta(days=1)

    with patch("timefence.usage.date") as mock_date:
        mock_date.today.return_value = yesterday
        add_usage(tmp_path, "roblox", 100, window_id="after_school")
        assert get_usage(tmp_path, "roblox") == 100

        mock_date.today.return_value = today
        assert get_usage(tmp_path, "roblox") == 0
        assert add_usage(tmp_path, "roblox", 15, window_id="evening")["total_usage_seconds"] == 15
        assert get_usage(tmp_path, "roblox", window_id="after_school") == 0
        assert get_usage(tmp_path, "roblox", window_id="evening") == 15


def test_load_state_uses_injected_now(tmp_path):
    when = datetime(2024, 1, 15, 16, 30)
    add_usage(tmp_path, "roblox", 12, window_id="after_school", now=when)
    assert load_state(tmp_path, "roblox", now=when)["date"] == "2024-01-15"
    assert (tmp_path / "roblox" / "2024-01-15.json").exists()


def test_watch_history_keeps_sequence_and_collapses_consecutive_same_id(tmp_path):
    a = {
        "id": "aaaaaaaaaaa",
        "title": "First",
        "channel": "Channel A",
        "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
    }
    b = {
        "id": "bbbbbbbbbbb",
        "title": "Second",
        "channel": "Channel B",
        "url": "https://www.youtube.com/watch?v=bbbbbbbbbbb",
    }
    t0 = datetime(2024, 1, 15, 16, 30, 0)
    t1 = datetime(2024, 1, 15, 16, 30, 15)
    t2 = datetime(2024, 1, 15, 16, 30, 30)
    t3 = datetime(2024, 1, 15, 16, 30, 45)

    add_usage(tmp_path, "youtube", 15, window_id="evening", now=t0, video=a)
    add_usage(tmp_path, "youtube", 15, window_id="evening", now=t1, video=a)
    add_usage(tmp_path, "youtube", 15, window_id="evening", now=t2, video=b)
    add_usage(tmp_path, "youtube", 15, window_id="evening", now=t3, video=a)

    state = load_state(tmp_path, "youtube", now=t0)
    assert [item["id"] for item in state["videos"]] == ["aaaaaaaaaaa", "bbbbbbbbbbb", "aaaaaaaaaaa"]
    assert state["videos"][0]["usage_seconds"] == 30
    assert state["videos"][0]["first_seen"] == "16:30:00"
    assert state["videos"][0]["last_seen"] == "16:30:15"
    assert state["videos"][1]["usage_seconds"] == 15
    assert state["videos"][2]["usage_seconds"] == 15
    assert state["videos"][2]["first_seen"] == "16:30:45"
    assert [item["channel"] for item in state["videos"]] == ["Channel A", "Channel B", "Channel A"]


def test_watch_history_fills_channel_on_later_poll(tmp_path):
    when = datetime(2024, 1, 15, 16, 30)
    add_usage(
        tmp_path,
        "youtube",
        15,
        window_id="evening",
        now=when,
        video={"id": "aaaaaaaaaaa", "title": "First", "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa"},
    )
    add_usage(
        tmp_path,
        "youtube",
        15,
        window_id="evening",
        now=datetime(2024, 1, 15, 16, 30, 15),
        video={
            "id": "aaaaaaaaaaa",
            "title": "First",
            "channel": "Channel A",
            "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
        },
    )
    assert load_state(tmp_path, "youtube", now=when)["videos"][0]["channel"] == "Channel A"


def test_note_video_appends_blocked_video_without_usage(tmp_path):
    when = datetime(2024, 1, 15, 19, 0)
    note_video(
        tmp_path,
        "youtube",
        {"id": "blockedvideo1", "title": "Nope", "url": "https://www.youtube.com/watch?v=blockedvideo1"},
        now=when,
    )
    state = load_state(tmp_path, "youtube", now=when)
    assert state["total_usage_seconds"] == 0
    assert [item["id"] for item in state["videos"]] == ["blockedvideo1"]
    assert state["videos"][0]["usage_seconds"] == 0


def test_load_state_preserves_duplicate_ids_in_watch_history(tmp_path):
    path = tmp_path / "youtube" / f"{date.today().isoformat()}.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps(
            {
                "total_usage_seconds": 30,
                "videos": [
                    {"id": "aaaaaaaaaaa", "title": "First", "usage_seconds": 15},
                    {"id": "bbbbbbbbbbb", "title": "Second", "usage_seconds": 15},
                    {"id": "aaaaaaaaaaa", "title": "First again", "usage_seconds": 15},
                    {"id": ""},
                ],
            }
        )
    )
    state = load_state(tmp_path, "youtube")
    assert [item["id"] for item in state["videos"]] == ["aaaaaaaaaaa", "bbbbbbbbbbb", "aaaaaaaaaaa"]
    assert state["videos"][2]["title"] == "First again"
