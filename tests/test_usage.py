import json
from datetime import date, datetime, timedelta
from unittest.mock import patch

from timefence.usage import add_usage, get_usage, load_state


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
