import json
from pathlib import Path

import pytest

from timefence.config import load_config, validate_config
from tests.helpers import make_config, make_day_policy, make_resource, make_window, write_rules


def test_load_config_returns_valid_document(app_dir):
    expected = make_config(revision=3)
    path = write_rules(app_dir, expected)
    assert load_config(path) == expected


def test_load_config_accepts_shipped_rules():
    shipped = Path(__file__).resolve().parents[1] / "config" / "rules.json"
    cfg = load_config(shipped)
    assert cfg["version"] == 1
    assert set(cfg["resources"]) >= {"roblox", "youtube"}
    roblox_windows = cfg["resources"]["roblox"]["policy"]["default"]["allowed_windows"]
    assert [window["id"] for window in roblox_windows] == ["after_school", "evening"]


@pytest.mark.parametrize(
    "payload",
    [
        {"version": 2, "resources": {}},
        {"version": "1", "resources": {}},
        {"resources": {}},
        {"version": 1, "resources": []},
        {"version": 1, "resources": None},
        {"version": 1},
    ],
)
def test_load_config_rejects_unsupported_or_invalid_documents(app_dir, payload):
    path = write_rules(app_dir, payload)
    with pytest.raises(ValueError, match="Unsupported or invalid config"):
        load_config(path)


def test_load_config_raises_when_file_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.json")


def test_load_config_raises_on_invalid_json(app_dir):
    path = app_dir / "config" / "rules.json"
    path.write_text("{not json")
    with pytest.raises(json.JSONDecodeError):
        load_config(path)


def test_rejects_window_without_id():
    cfg = make_config(
        resources={
            "roblox": make_resource(
                default=make_day_policy(allowed_windows=[{"start": "16:00", "end": "18:00"}])
            )
        }
    )
    with pytest.raises(ValueError, match="missing a stable id"):
        validate_config(cfg)


def test_rejects_duplicate_window_ids():
    cfg = make_config(
        resources={
            "roblox": make_resource(
                default=make_day_policy(
                    allowed_windows=[
                        make_window("after_school", "16:00", "18:00"),
                        make_window("after_school", "19:00", "20:00"),
                    ]
                )
            )
        }
    )
    with pytest.raises(ValueError, match="duplicate window id"):
        validate_config(cfg)


def test_rejects_invalid_time_and_negative_limits():
    with pytest.raises(ValueError, match="HH:MM"):
        validate_config(
            make_config(
                resources={
                    "roblox": make_resource(
                        default=make_day_policy(allowed_windows=[make_window("x", "16", "18:00")])
                    )
                }
            )
        )
    with pytest.raises(ValueError, match="non-negative"):
        validate_config(
            make_config(
                resources={"roblox": make_resource(default=make_day_policy(daily_limit_minutes=-1))}
            )
        )


def test_rejects_unknown_day_name_and_bad_date_override():
    with pytest.raises(ValueError, match="unknown day"):
        validate_config(
            make_config(resources={"roblox": make_resource(days={"funday": make_day_policy()})})
        )
    with pytest.raises(ValueError, match="invalid date override"):
        validate_config(
            make_config(
                resources={"roblox": make_resource(date_overrides={"12/25/2026": make_day_policy()})}
            )
        )


def test_rejects_missing_allowed_windows_array():
    with pytest.raises(ValueError, match="allowed_windows is required"):
        validate_config(
            make_config(
                resources={"roblox": make_resource(default={"daily_limit_minutes": 30})}
            )
        )
