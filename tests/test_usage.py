import json
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from timefence.usage import add_usage, get_usage


def test_get_usage_returns_zero_when_file_missing(tmp_path):
    assert get_usage(tmp_path, "roblox") == 0


def test_get_usage_reads_usage_seconds(tmp_path):
    path = tmp_path / "roblox" / f"{date.today().isoformat()}.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"usage_seconds": 120}))
    assert get_usage(tmp_path, "roblox") == 120


def test_get_usage_defaults_missing_usage_seconds_to_zero(tmp_path):
    path = tmp_path / "roblox" / f"{date.today().isoformat()}.json"
    path.parent.mkdir()
    path.write_text(json.dumps({}))
    assert get_usage(tmp_path, "roblox") == 0


def test_get_usage_rejects_invalid_json(tmp_path):
    path = tmp_path / "roblox" / f"{date.today().isoformat()}.json"
    path.parent.mkdir()
    path.write_text("not-json")
    with pytest.raises(json.JSONDecodeError):
        get_usage(tmp_path, "roblox")


def test_add_usage_creates_file_and_returns_total(tmp_path):
    total = add_usage(tmp_path, "youtube", 15)
    assert total == 15
    assert get_usage(tmp_path, "youtube") == 15
    path = tmp_path / "youtube" / f"{date.today().isoformat()}.json"
    assert json.loads(path.read_text()) == {"usage_seconds": 15}
    assert not path.with_suffix(".tmp").exists()


def test_add_usage_accumulates(tmp_path):
    add_usage(tmp_path, "roblox", 15)
    assert add_usage(tmp_path, "roblox", 15) == 30
    assert get_usage(tmp_path, "roblox") == 30


def test_usage_is_isolated_per_resource(tmp_path):
    add_usage(tmp_path, "roblox", 10)
    add_usage(tmp_path, "youtube", 20)
    assert get_usage(tmp_path, "roblox") == 10
    assert get_usage(tmp_path, "youtube") == 20


def test_usage_resets_on_a_new_day(tmp_path):
    today = date(2024, 1, 15)
    yesterday = today - timedelta(days=1)

    with patch("timefence.usage.date") as mock_date:
        mock_date.today.return_value = yesterday
        add_usage(tmp_path, "roblox", 100)
        assert get_usage(tmp_path, "roblox") == 100

        mock_date.today.return_value = today
        assert get_usage(tmp_path, "roblox") == 0
        assert add_usage(tmp_path, "roblox", 15) == 15
