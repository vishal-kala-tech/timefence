import json
from pathlib import Path

import pytest

from timefence.config import load_config, save_config, validate_config, validate_resource
from tests.helpers import make_config, make_day_policy, make_resource, make_window, write_rules

SHIPPED_IDENTITIES = {
    ("app", "com.roblox.Roblox"),
    ("app", "com.google.Chrome"),
    ("app", "com.apple.Safari"),
    ("app", "com.microsoft.VSCode"),
    ("app", "com.todesktop.230313mzl4w4u92"),
    ("app", "com.jetbrains.pycharm"),
    ("video_category", "youtube_videos"),
    ("video_category", "youtube_shorts"),
    ("website", "youtube.com"),
}


def _by_key(cfg):
    return {(item["resource_type"], item["resource_id"]): item for item in cfg["resources"]}


def test_load_config_returns_valid_document(app_dir):
    expected = make_config(revision=3)
    path = write_rules(app_dir, expected)
    assert load_config(path) == expected


def test_load_config_accepts_shipped_rules():
    shipped = Path(__file__).resolve().parents[1] / "config" / "rules.json"
    cfg = load_config(shipped)
    assert cfg["version"] == 1
    assert isinstance(cfg["resources"], list)
    identities = {(item["resource_type"], item["resource_id"]) for item in cfg["resources"]}
    assert identities >= SHIPPED_IDENTITIES
    resources = _by_key(cfg)
    youtube = resources[("video_category", "youtube_videos")]
    assert youtube["browsers"] == ["chrome", "safari"]
    assert "youtube.com/watch" in youtube["url_contains"]
    assert resources[("video_category", "youtube_shorts")]["url_contains"] == ["youtube.com/shorts"]
    assert resources[("app", "com.apple.Safari")]["resource_id"] == "com.apple.Safari"
    assert cfg.get("log_browsing") is True
    assert "com.roblox.RobloxPlayer" in resources[("app", "com.roblox.Roblox")]["match_ids"]
    assert resources[("app", "com.todesktop.230313mzl4w4u92")]["resource_id"] == "com.todesktop.230313mzl4w4u92"
    assert "com.microsoft.VSCode" in resources[("app", "com.microsoft.VSCode")]["match_ids"]
    assert "com.google.Chrome" in resources[("app", "com.google.Chrome")]["match_ids"]
    assert "com.jetbrains.pycharm" in resources[("app", "com.jetbrains.pycharm")]["match_ids"]
    assert cfg.get("screen_time", {}).get("idle_threshold_seconds") == 120
    roblox_windows = resources[("app", "com.roblox.Roblox")]["policy"]["default"]["allowed_windows"]
    assert [window["id"] for window in roblox_windows] == ["after_school", "evening"]


def test_load_config_accepts_empty_resources_list():
    assert validate_config({"version": 1, "resources": []})["resources"] == []


@pytest.mark.parametrize(
    "payload",
    [
        {"version": 2, "resources": {}},
        {"version": "1", "resources": {}},
        {"resources": {}},
        {"version": 1, "resources": {}},
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
        resources=[
            make_resource(default=make_day_policy(allowed_windows=[{"start": "16:00", "end": "18:00"}]))
        ]
    )
    with pytest.raises(ValueError, match="missing a stable id"):
        validate_config(cfg)


def test_rejects_duplicate_window_ids():
    cfg = make_config(
        resources=[
            make_resource(
                default=make_day_policy(
                    allowed_windows=[
                        make_window("after_school", "16:00", "18:00"),
                        make_window("after_school", "19:00", "20:00"),
                    ]
                )
            )
        ]
    )
    with pytest.raises(ValueError, match="duplicate window id"):
        validate_config(cfg)


def test_rejects_invalid_time_and_negative_limits():
    with pytest.raises(ValueError, match="HH:MM"):
        validate_config(
            make_config(
                resources=[make_resource(default=make_day_policy(allowed_windows=[make_window("x", "16", "18:00")]))]
            )
        )
    with pytest.raises(ValueError, match="non-negative"):
        validate_config(make_config(resources=[make_resource(default=make_day_policy(daily_limit_minutes=-1))]))


def test_rejects_unknown_day_name_and_bad_date_override():
    with pytest.raises(ValueError, match="unknown day"):
        validate_config(make_config(resources=[make_resource(days={"funday": make_day_policy()})]))
    with pytest.raises(ValueError, match="invalid date override"):
        validate_config(
            make_config(resources=[make_resource(date_overrides={"12/25/2026": make_day_policy()})])
        )


def test_allows_day_policy_without_allowed_windows():
    cfg = make_config(resources=[make_resource(default={"daily_limit_minutes": 30})])
    assert "allowed_windows" not in validate_config(cfg)["resources"][0]["policy"]["default"]


def test_rejects_non_array_allowed_windows():
    with pytest.raises(ValueError, match="allowed_windows must be an array"):
        validate_config(
            make_config(
                resources=[make_resource(default={"daily_limit_minutes": 30, "allowed_windows": "nope"})]
            )
        )


def test_rejects_invalid_warning_minutes():
    with pytest.raises(ValueError, match="must be an array"):
        validate_config(make_config(resources=[make_resource(default=make_day_policy(warning_minutes=5))]))
    with pytest.raises(ValueError, match="positive number"):
        validate_config(
            make_config(resources=[make_resource(default=make_day_policy(warning_minutes=[10, 0]))])
        )
    with pytest.raises(ValueError, match="duplicate value"):
        validate_config(
            make_config(resources=[make_resource(default=make_day_policy(warning_minutes=[5, 5]))])
        )
    with pytest.raises(ValueError, match="exceeds the 45-minute limit"):
        validate_config(
            make_config(
                resources=[
                    make_resource(default=make_day_policy(daily_limit_minutes=45, warning_minutes=[10, 60]))
                ]
            )
        )


def test_rejects_invalid_url_filters():
    with pytest.raises(ValueError, match="url_contains"):
        validate_config(make_config(resources=[make_resource(url_contains="youtube.com/watch")]))
    with pytest.raises(ValueError, match="url_excludes"):
        validate_config(make_config(resources=[make_resource(url_excludes=[""])]))


def test_allows_warning_minutes_when_no_limit_exists():
    cfg = make_config(
        resources=[make_resource(default=make_day_policy(daily_limit_minutes=0, warning_minutes=[10, 5]))]
    )
    assert validate_config(cfg)["resources"][0]["policy"]["default"]["warning_minutes"] == [10, 5]


def test_rejects_non_boolean_log_browsing():
    cfg = make_config(log_browsing="yes")
    with pytest.raises(ValueError, match="log_browsing must be a boolean"):
        validate_config(cfg)


def test_rejects_invalid_status_port():
    cfg = make_config()
    cfg["status_port"] = 0
    with pytest.raises(ValueError, match="status_port"):
        validate_config(cfg)
    cfg["status_port"] = True
    with pytest.raises(ValueError, match="status_port"):
        validate_config(cfg)


def test_accepts_status_page_settings():
    cfg = make_config()
    cfg["status_page"] = False
    cfg["status_port"] = 8743
    assert validate_config(cfg)["status_port"] == 8743


def test_save_config_replaces_file_atomically(app_dir):
    path = write_rules(app_dir, make_config(revision=1))
    saved = save_config(path, make_config(revision=9, log_browsing=True))
    assert saved["revision"] == 9
    assert load_config(path)["revision"] == 9
    assert not path.with_suffix(".tmp").exists()
    with pytest.raises(ValueError, match="Unsupported or invalid config"):
        save_config(path, {"version": 2, "resources": {}})


def test_accepts_match_ids_and_screen_time_settings():
    cfg = make_config(
        resources=[
            make_resource(
                resource_type="app",
                resource_id="com.roblox.Roblox",
                match_ids=["com.roblox.RobloxPlayer", "com.roblox.Roblox"],
            )
        ]
    )
    cfg["screen_time"] = {
        "enabled": True,
        "poll_interval_seconds": 10,
        "idle_threshold_seconds": 120,
        "max_countable_interval_seconds": 30,
    }
    saved = validate_config(cfg)
    assert saved["resources"][0]["match_ids"] == ["com.roblox.RobloxPlayer", "com.roblox.Roblox"]
    assert saved["screen_time"]["poll_interval_seconds"] == 10


def test_rejects_invalid_match_ids_and_screen_time():
    with pytest.raises(ValueError, match="match_ids"):
        validate_config(make_config(resources=[make_resource(match_ids="com.roblox.Roblox")]))
    cfg = make_config()
    cfg["screen_time"] = {"idle_threshold_seconds": -1}
    with pytest.raises(ValueError, match="idle_threshold_seconds"):
        validate_config(cfg)


def test_validate_resource_takes_a_resource_dict():
    validate_resource(make_resource())
    with pytest.raises(ValueError, match="must be an object"):
        validate_resource("roblox")
