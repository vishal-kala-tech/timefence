import json
import sqlite3
from pathlib import Path

import pytest

from timefence.config import load_config, save_config, sqlite_path_for_rules, validate_config
from timefence.identity import (
    RESOURCE_TYPE_APP,
    RESOURCE_TYPE_VIDEO_CATEGORY,
    RESOURCE_TYPE_WEBSITE,
    YOUTUBE_SHORTS_RESOURCE_ID,
    YOUTUBE_VIDEOS_RESOURCE_ID,
    YOUTUBE_WEBSITE_RESOURCE_ID,
)
from timefence.policy import limit_seconds
from timefence.rules_store import (
    WEEKDAY_NAME_TO_DOW,
    fetch_effective_policy,
    has_rules,
    load_rules,
    save_rules,
)
from timefence.tracking.sqlite_usage_store import SqliteUsageStore
from tests.helpers import make_config, make_day_policy, make_resource, make_window, write_rules

SHIPPED = Path(__file__).resolve().parents[1] / "config" / "rules.json"


def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _save(tmp_path, cfg):
    db = tmp_path / "screen_time.sqlite"
    save_rules(db, validate_config(cfg))
    return db


def test_sqlite_path_only_for_app_layout(app_dir, tmp_path):
    assert sqlite_path_for_rules(app_dir / "config" / "rules.json") == app_dir / "state" / "screen_time.sqlite"
    assert sqlite_path_for_rules(tmp_path / "missing.json") is None
    assert sqlite_path_for_rules(SHIPPED) is None


def test_save_config_writes_rule_tables(app_dir):
    path = write_rules(app_dir, make_config(revision=3, log_browsing=True))
    save_config(
        path,
        make_config(
            revision=4,
            log_browsing=False,
            resources=[
                make_resource(
                    resource_id="com.apple.Terminal",
                    display_name="Terminal",
                    default=make_day_policy(
                        daily_limit_minutes=20,
                        warning_minutes=[5],
                        allowed_windows=[make_window("evening", "19:00", "21:00", limit_minutes=20)],
                    ),
                )
            ],
        ),
    )
    db = sqlite_path_for_rules(path)
    assert has_rules(db)
    loaded = load_config(path)
    assert loaded["revision"] == 4
    assert loaded["log_browsing"] is False
    terminal = loaded["resources"][0]
    assert terminal["resource_id"] == "com.apple.Terminal"
    assert terminal["display_name"] == "Terminal"
    assert terminal["policy"]["default"]["daily_limit_minutes"] == 20
    assert terminal["policy"]["default"]["allowed_windows"][0]["id"] == "evening"
    conn = _connect(db)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'rule_%'")
    }
    assert "rule_settings" in tables
    assert "rule_screen_time_settings" in tables
    assert "rule_resources" in tables
    assert "rule_resource_match_ids" in tables
    assert "rule_policies" in tables
    assert "rule_windows" in tables
    assert "rule_match_ids" not in tables
    assert conn.execute("SELECT COUNT(*) FROM rule_resources").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM rule_windows").fetchone()[0] == 1
    conn.close()


def test_load_prefers_database_after_import(app_dir):
    original = make_config(revision=2, log_browsing=True)
    path = write_rules(app_dir, original)
    first = load_config(path)
    assert first["revision"] == 2
    path.write_text(json.dumps(make_config(revision=99, log_browsing=False)))
    second = load_config(path)
    assert second["revision"] == 2
    assert second["log_browsing"] is True


def test_round_trip_shipped_rules_through_db(app_dir):
    cfg = validate_config(json.loads(SHIPPED.read_text()))
    db = app_dir / "state" / "screen_time.sqlite"
    save_rules(db, cfg)
    loaded = validate_config(load_rules(db))
    by_key = {(item["resource_type"], item["resource_id"]): item for item in loaded["resources"]}
    original = {(item["resource_type"], item["resource_id"]): item for item in cfg["resources"]}
    assert set(by_key) == set(original)
    roblox = by_key[(RESOURCE_TYPE_APP, "com.roblox.Roblox")]
    assert roblox["display_name"] == "Roblox"
    assert "com.roblox.RobloxPlayer" in roblox["match_ids"]
    assert [window["id"] for window in roblox["policy"]["default"]["allowed_windows"]] == [
        "after_school",
        "evening",
    ]
    youtube = by_key[(RESOURCE_TYPE_VIDEO_CATEGORY, YOUTUBE_VIDEOS_RESOURCE_ID)]
    assert "youtube.com/watch" in youtube["url_contains"]
    assert youtube["url_excludes"] == ["youtube.com/shorts"]
    assert loaded["screen_time"]["idle_threshold_seconds"] == 120
    assert loaded["log_browsing"] is True


def test_global_and_screen_time_settings_persist(tmp_path):
    db = _save(
        tmp_path,
        make_config(
            revision=8,
            check_interval_seconds=20,
            log_browsing=True,
            resources=[make_resource()],
        )
        | {
            "screen_time": {
                "enabled": False,
                "poll_interval_seconds": 9,
                "idle_threshold_seconds": 90,
                "max_countable_interval_seconds": 25,
            }
        },
    )
    conn = _connect(db)
    settings = conn.execute("SELECT * FROM rule_settings WHERE id = 1").fetchone()
    screen = conn.execute("SELECT * FROM rule_screen_time_settings WHERE id = 1").fetchone()
    conn.close()
    assert settings["version"] == 1
    assert settings["revision"] == 8
    assert settings["check_interval_seconds"] == 20
    assert settings["log_browsing"] == 1
    assert screen["enabled"] == 0
    assert screen["poll_interval_seconds"] == 9
    assert screen["idle_threshold_seconds"] == 90
    assert screen["max_countable_interval_seconds"] == 25
    loaded = load_rules(db)
    assert loaded["screen_time"]["enabled"] is False
    assert loaded["screen_time"]["poll_interval_seconds"] == 9


def test_resource_match_ids_browsers_and_url_filters(tmp_path):
    db = _save(
        tmp_path,
        make_config(
            resources=[
                make_resource(
                    resource_type=RESOURCE_TYPE_VIDEO_CATEGORY,
                    resource_id=YOUTUBE_VIDEOS_RESOURCE_ID,
                    display_name="YouTube Videos",
                    module="youtube",
                    match_ids=["youtube_videos"],
                    browsers=["chrome", "safari"],
                    url_contains=["youtube.com/watch", "youtu.be/"],
                    url_excludes=["youtube.com/shorts"],
                    default=make_day_policy(daily_limit_minutes=30),
                )
            ]
        ),
    )
    conn = _connect(db)
    resource = conn.execute(
        "SELECT * FROM rule_resources WHERE resource_id = ?",
        (YOUTUBE_VIDEOS_RESOURCE_ID,),
    ).fetchone()
    assert resource["resource_type"] == RESOURCE_TYPE_VIDEO_CATEGORY
    assert resource["display_name"] == "YouTube Videos"
    assert resource["module"] == "youtube"
    assert resource["enabled"] == 1
    match_ids = [
        row["match_id"]
        for row in conn.execute(
            "SELECT match_id FROM rule_resource_match_ids WHERE resource_id = ? ORDER BY rowid",
            (YOUTUBE_VIDEOS_RESOURCE_ID,),
        )
    ]
    browsers = [
        row["browser"]
        for row in conn.execute(
            "SELECT browser FROM rule_resource_browsers WHERE resource_id = ? ORDER BY rowid",
            (YOUTUBE_VIDEOS_RESOURCE_ID,),
        )
    ]
    includes = [
        row["pattern"]
        for row in conn.execute(
            """
            SELECT pattern FROM rule_url_filters
            WHERE resource_id = ? AND filter_type = 'include' ORDER BY id
            """,
            (YOUTUBE_VIDEOS_RESOURCE_ID,),
        )
    ]
    excludes = [
        row["pattern"]
        for row in conn.execute(
            """
            SELECT pattern FROM rule_url_filters
            WHERE resource_id = ? AND filter_type = 'exclude' ORDER BY id
            """,
            (YOUTUBE_VIDEOS_RESOURCE_ID,),
        )
    ]
    conn.close()
    assert match_ids == ["youtube_videos"]
    assert browsers == ["chrome", "safari"]
    assert includes == ["youtube.com/watch", "youtu.be/"]
    assert excludes == ["youtube.com/shorts"]


def test_alternate_match_ids_for_apps(tmp_path):
    db = _save(
        tmp_path,
        make_config(
            resources=[
                make_resource(
                    resource_id="com.roblox.Roblox",
                    display_name="Roblox",
                    match_ids=["com.roblox.RobloxPlayer", "com.roblox.Roblox"],
                ),
                make_resource(
                    resource_id="com.microsoft.VSCode",
                    display_name="VS Code",
                    match_ids=[
                        "com.microsoft.VSCode",
                        "com.microsoft.VSCodeInsiders",
                        "com.microsoft.visual-studio",
                    ],
                ),
            ]
        ),
    )
    conn = _connect(db)
    roblox = {
        row["match_id"]
        for row in conn.execute(
            "SELECT match_id FROM rule_resource_match_ids WHERE resource_id = 'com.roblox.Roblox'"
        )
    }
    vscode = {
        row["match_id"]
        for row in conn.execute(
            "SELECT match_id FROM rule_resource_match_ids WHERE resource_id = 'com.microsoft.VSCode'"
        )
    }
    conn.close()
    assert roblox == {"com.roblox.RobloxPlayer", "com.roblox.Roblox"}
    assert vscode == {
        "com.microsoft.VSCode",
        "com.microsoft.VSCodeInsiders",
        "com.microsoft.visual-studio",
    }


def test_default_saturday_sunday_policies_and_warnings(tmp_path):
    db = _save(
        tmp_path,
        make_config(
            resources=[
                make_resource(
                    resource_id="com.roblox.Roblox",
                    display_name="Roblox",
                    default=make_day_policy(
                        daily_limit_minutes=45,
                        warning_minutes=[10, 5, 1],
                        allowed_windows=[
                            make_window(
                                "after_school",
                                "16:00",
                                "18:00",
                                limit_minutes=30,
                                warning_minutes=[5, 1],
                            )
                        ],
                    ),
                    days={
                        "saturday": make_day_policy(daily_limit_minutes=120, warning_minutes=[10]),
                        "sunday": make_day_policy(daily_limit_minutes=90, warning_minutes=[5]),
                    },
                )
            ]
        ),
    )
    conn = _connect(db)
    policies = {
        (row["policy_type"], row["day_of_week"]): row
        for row in conn.execute(
            "SELECT * FROM rule_policies WHERE resource_id = 'com.roblox.Roblox'"
        )
    }
    assert set(policies) == {("default", None), ("day", 6), ("day", 0)}
    assert policies[("default", None)]["daily_limit_minutes"] == 45
    assert policies[("day", 6)]["daily_limit_minutes"] == 120
    assert policies[("day", 0)]["daily_limit_minutes"] == 90
    default_id = policies[("default", None)]["policy_id"]
    warnings = [
        row["warning_minutes"]
        for row in conn.execute(
            "SELECT warning_minutes FROM rule_policy_warnings WHERE policy_id = ? ORDER BY warning_minutes DESC",
            (default_id,),
        )
    ]
    window = conn.execute(
        "SELECT * FROM rule_windows WHERE policy_id = ?",
        (default_id,),
    ).fetchone()
    window_warnings = [
        row["warning_minutes"]
        for row in conn.execute(
            "SELECT warning_minutes FROM rule_window_warnings WHERE window_id = ? ORDER BY warning_minutes DESC",
            (window["window_id"],),
        )
    ]
    conn.close()
    assert warnings == [10, 5, 1]
    assert window["window_key"] == "after_school"
    assert window["start_time"] == "16:00"
    assert window["end_time"] == "18:00"
    assert window["limit_minutes"] == 30
    assert window_warnings == [5, 1]
    loaded = load_rules(db)["resources"][0]["policy"]
    assert loaded["days"]["saturday"]["daily_limit_minutes"] == 120
    assert loaded["days"]["sunday"]["daily_limit_minutes"] == 90


def test_day_of_week_mapping_and_date_overrides(tmp_path):
    db = _save(
        tmp_path,
        make_config(
            resources=[
                make_resource(
                    resource_id="com.google.Chrome",
                    display_name="Chrome",
                    default=make_day_policy(daily_limit_minutes=0, allowed_windows=None),
                    days={
                        "monday": make_day_policy(daily_limit_minutes=10),
                        "friday": make_day_policy(daily_limit_minutes=20),
                    },
                    date_overrides={"2026-12-25": make_day_policy(daily_limit_minutes=0, allowed_windows=None)},
                )
            ]
        ),
    )
    conn = _connect(db)
    days = {
        row["day_of_week"]: row["daily_limit_minutes"]
        for row in conn.execute(
            "SELECT day_of_week, daily_limit_minutes FROM rule_policies WHERE policy_type = 'day'"
        )
    }
    dated = conn.execute(
        "SELECT policy_date, daily_limit_minutes FROM rule_policies WHERE policy_type = 'date'"
    ).fetchone()
    christmas = fetch_effective_policy(conn, "com.google.Chrome", "2026-12-25")
    friday = fetch_effective_policy(conn, "com.google.Chrome", "2026-12-18")
    tuesday = fetch_effective_policy(conn, "com.google.Chrome", "2026-12-22")
    conn.close()
    assert WEEKDAY_NAME_TO_DOW["sunday"] == 0
    assert WEEKDAY_NAME_TO_DOW["saturday"] == 6
    assert days == {1: 10, 5: 20}
    assert dated["policy_date"] == "2026-12-25"
    assert christmas["policy_type"] == "date"
    assert friday["policy_type"] == "day"
    assert friday["day_of_week"] == 5
    assert tuesday["policy_type"] == "default"


def test_daily_limit_zero_is_unlimited_and_does_not_block(tmp_path):
    db = _save(
        tmp_path,
        make_config(
            resources=[
                make_resource(
                    resource_id="com.google.Chrome",
                    display_name="Google Chrome",
                    default={"daily_limit_minutes": 0},
                )
            ]
        ),
    )
    conn = _connect(db)
    policy = conn.execute(
        "SELECT * FROM rule_policies WHERE resource_id = 'com.google.Chrome' AND policy_type = 'default'"
    ).fetchone()
    windows = conn.execute(
        "SELECT COUNT(*) FROM rule_windows WHERE policy_id = ?",
        (policy["policy_id"],),
    ).fetchone()[0]
    conn.close()
    assert policy["daily_limit_minutes"] == 0
    assert windows == 0
    assert limit_seconds(0) == 0
    loaded = load_rules(db)["resources"][0]
    assert loaded["policy"]["default"]["daily_limit_minutes"] == 0
    assert "allowed_windows" not in loaded["policy"]["default"]


def test_empty_allowed_windows_round_trip(tmp_path):
    db = _save(
        tmp_path,
        make_config(
            resources=[
                make_resource(
                    resource_id="com.roblox.Roblox",
                    display_name="Roblox",
                    default=make_day_policy(daily_limit_minutes=30, allowed_windows=[]),
                )
            ]
        ),
    )
    loaded = load_rules(db)["resources"][0]["policy"]["default"]
    assert loaded["allowed_windows"] == []
    conn = _connect(db)
    row = conn.execute(
        "SELECT has_windows FROM rule_policies WHERE resource_id = 'com.roblox.Roblox'"
    ).fetchone()
    assert row["has_windows"] == 1
    assert conn.execute("SELECT COUNT(*) FROM rule_windows").fetchone()[0] == 0
    conn.close()


def test_youtube_videos_and_shorts_ids(tmp_path):
    db = _save(
        tmp_path,
        make_config(
            resources=[
                make_resource(
                    resource_type=RESOURCE_TYPE_VIDEO_CATEGORY,
                    resource_id=YOUTUBE_VIDEOS_RESOURCE_ID,
                    display_name="YouTube Videos",
                    url_contains=["youtube.com/watch", "youtu.be/"],
                    url_excludes=["youtube.com/shorts"],
                    browsers=["chrome", "safari"],
                    default=make_day_policy(daily_limit_minutes=30),
                ),
                make_resource(
                    resource_type=RESOURCE_TYPE_VIDEO_CATEGORY,
                    resource_id=YOUTUBE_SHORTS_RESOURCE_ID,
                    display_name="YouTube Shorts",
                    url_contains=["youtube.com/shorts"],
                    browsers=["chrome", "safari"],
                    default=make_day_policy(daily_limit_minutes=15),
                ),
                make_resource(
                    resource_type=RESOURCE_TYPE_WEBSITE,
                    resource_id=YOUTUBE_WEBSITE_RESOURCE_ID,
                    display_name="YouTube",
                    default=make_day_policy(daily_limit_minutes=0, allowed_windows=None),
                ),
            ]
        ),
    )
    conn = _connect(db)
    ids = {
        row["resource_id"]
        for row in conn.execute("SELECT resource_id FROM rule_resources")
    }
    shorts_includes = [
        row["pattern"]
        for row in conn.execute(
            "SELECT pattern FROM rule_url_filters WHERE resource_id = ? AND filter_type = 'include'",
            (YOUTUBE_SHORTS_RESOURCE_ID,),
        )
    ]
    conn.close()
    assert ids == {
        YOUTUBE_VIDEOS_RESOURCE_ID,
        YOUTUBE_SHORTS_RESOURCE_ID,
        YOUTUBE_WEBSITE_RESOURCE_ID,
    }
    assert "youtube" not in ids
    assert shorts_includes == ["youtube.com/shorts"]


def test_cascade_delete_resource_removes_children(tmp_path):
    db = _save(
        tmp_path,
        make_config(
            resources=[
                make_resource(
                    resource_id="com.roblox.Roblox",
                    match_ids=["com.roblox.RobloxPlayer"],
                    default=make_day_policy(
                        daily_limit_minutes=45,
                        warning_minutes=[10],
                        allowed_windows=[
                            make_window("evening", "19:00", "20:30", limit_minutes=30, warning_minutes=[5])
                        ],
                    ),
                )
            ]
        ),
    )
    conn = _connect(db)
    conn.execute("DELETE FROM rule_resources WHERE resource_id = 'com.roblox.Roblox'")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM rule_resource_match_ids").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM rule_policies").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM rule_policy_warnings").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM rule_windows").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM rule_window_warnings").fetchone()[0] == 0
    conn.close()


def test_duplicate_prevention(tmp_path):
    db = _save(tmp_path, make_config(resources=[make_resource(resource_id="com.roblox.Roblox")]))
    conn = _connect(db)
    policy_id = conn.execute(
        "SELECT policy_id FROM rule_policies WHERE resource_id = 'com.roblox.Roblox'"
    ).fetchone()[0]

    def reject(sql, params=()):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql, params)
        conn.rollback()

    reject(
        "INSERT INTO rule_resources (resource_id, resource_type, display_name) VALUES (?, ?, ?)",
        ("com.roblox.Roblox", "app", "Roblox"),
    )
    reject(
        "INSERT INTO rule_policies (resource_id, policy_type, daily_limit_minutes) VALUES (?, ?, ?)",
        ("com.roblox.Roblox", "default", 10),
    )
    conn.execute(
        """
        INSERT INTO rule_policies (resource_id, policy_type, day_of_week, daily_limit_minutes)
        VALUES (?, 'day', 6, 10)
        """,
        ("com.roblox.Roblox",),
    )
    conn.commit()
    reject(
        """
        INSERT INTO rule_policies (resource_id, policy_type, day_of_week, daily_limit_minutes)
        VALUES (?, 'day', 6, 20)
        """,
        ("com.roblox.Roblox",),
    )
    conn.execute(
        """
        INSERT INTO rule_url_filters (resource_id, filter_type, pattern)
        VALUES (?, 'include', 'youtube.com/watch')
        """,
        ("com.roblox.Roblox",),
    )
    conn.commit()
    reject(
        """
        INSERT INTO rule_url_filters (resource_id, filter_type, pattern)
        VALUES (?, 'include', 'youtube.com/watch')
        """,
        ("com.roblox.Roblox",),
    )
    reject(
        "INSERT INTO rule_policy_warnings (policy_id, warning_minutes) VALUES (?, 0)",
        (policy_id,),
    )
    conn.close()


def test_save_rules_rolls_back_on_failure(tmp_path, monkeypatch):
    db = _save(
        tmp_path,
        make_config(
            revision=3,
            log_browsing=True,
            resources=[make_resource(resource_id="com.roblox.Roblox", display_name="Roblox")],
        ),
    )

    def boom(*args, **kwargs):
        raise RuntimeError("failed to persist resource")

    monkeypatch.setattr("timefence.rules_store._insert_resource", boom)
    with pytest.raises(RuntimeError, match="failed to persist resource"):
        save_rules(
            db,
            make_config(
                revision=9,
                log_browsing=False,
                resources=[make_resource(resource_id="com.google.Chrome", display_name="Chrome")],
            ),
        )
    loaded = load_rules(db)
    assert loaded["revision"] == 3
    assert loaded["log_browsing"] is True
    assert loaded["resources"][0]["resource_id"] == "com.roblox.Roblox"
    conn = _connect(db)
    assert conn.execute("SELECT COUNT(*) FROM rule_resources").fetchone()[0] == 1
    conn.close()


def test_usage_activity_does_not_create_rule_resources(tmp_path):
    db = tmp_path / "screen_time.sqlite"
    store = SqliteUsageStore(db)
    store.ensure_resource("app", "com.apple.Safari", display_name="Safari")
    conn = _connect(db)
    assert conn.execute("SELECT COUNT(*) FROM resources").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM rule_resources").fetchone()[0] == 0
    conn.close()


def test_loads_shipped_json_into_normalized_rows(tmp_path):
    cfg = validate_config(json.loads(SHIPPED.read_text()))
    db = tmp_path / "screen_time.sqlite"
    save_rules(db, cfg)
    conn = _connect(db)
    settings = conn.execute("SELECT * FROM rule_settings WHERE id = 1").fetchone()
    screen = conn.execute("SELECT * FROM rule_screen_time_settings WHERE id = 1").fetchone()
    videos = conn.execute(
        "SELECT * FROM rule_resources WHERE resource_id = ?",
        (YOUTUBE_VIDEOS_RESOURCE_ID,),
    ).fetchone()
    shorts = conn.execute(
        "SELECT * FROM rule_resources WHERE resource_id = ?",
        (YOUTUBE_SHORTS_RESOURCE_ID,),
    ).fetchone()
    website = conn.execute(
        "SELECT * FROM rule_resources WHERE resource_id = ?",
        (YOUTUBE_WEBSITE_RESOURCE_ID,),
    ).fetchone()
    video_includes = {
        row["pattern"]
        for row in conn.execute(
            "SELECT pattern FROM rule_url_filters WHERE resource_id = ? AND filter_type = 'include'",
            (YOUTUBE_VIDEOS_RESOURCE_ID,),
        )
    }
    video_excludes = {
        row["pattern"]
        for row in conn.execute(
            "SELECT pattern FROM rule_url_filters WHERE resource_id = ? AND filter_type = 'exclude'",
            (YOUTUBE_VIDEOS_RESOURCE_ID,),
        )
    }
    shorts_includes = {
        row["pattern"]
        for row in conn.execute(
            "SELECT pattern FROM rule_url_filters WHERE resource_id = ? AND filter_type = 'include'",
            (YOUTUBE_SHORTS_RESOURCE_ID,),
        )
    }
    browsers = {
        row["browser"]
        for row in conn.execute(
            "SELECT browser FROM rule_resource_browsers WHERE resource_id = ?",
            (YOUTUBE_VIDEOS_RESOURCE_ID,),
        )
    }
    roblox_days = {
        row["day_of_week"]: row["daily_limit_minutes"]
        for row in conn.execute(
            """
            SELECT day_of_week, daily_limit_minutes FROM rule_policies
            WHERE resource_id = 'com.roblox.Roblox' AND policy_type = 'day'
            """
        )
    }
    roblox_default = conn.execute(
        """
        SELECT policy_id, daily_limit_minutes FROM rule_policies
        WHERE resource_id = 'com.roblox.Roblox' AND policy_type = 'default'
        """
    ).fetchone()
    roblox_windows = {
        row["window_key"]
        for row in conn.execute(
            "SELECT window_key FROM rule_windows WHERE policy_id = ?",
            (roblox_default["policy_id"],),
        )
    }
    chrome_limit = conn.execute(
        """
        SELECT daily_limit_minutes FROM rule_policies
        WHERE resource_id = 'com.google.Chrome' AND policy_type = 'default'
        """
    ).fetchone()[0]
    conn.close()
    assert settings["log_browsing"] == 1
    assert settings["check_interval_seconds"] == 15
    assert screen["enabled"] == 1
    assert screen["poll_interval_seconds"] == 10
    assert screen["idle_threshold_seconds"] == 120
    assert videos["resource_type"] == RESOURCE_TYPE_VIDEO_CATEGORY
    assert videos["display_name"] == "YouTube Videos"
    assert shorts["resource_type"] == RESOURCE_TYPE_VIDEO_CATEGORY
    assert website["resource_type"] == RESOURCE_TYPE_WEBSITE
    assert video_includes == {"youtube.com/watch", "youtu.be/"}
    assert video_excludes == {"youtube.com/shorts"}
    assert shorts_includes == {"youtube.com/shorts"}
    assert browsers == {"chrome", "safari"}
    assert roblox_days[6] == 120
    assert roblox_days[0] == 120
    assert roblox_windows == {"after_school", "evening"}
    assert chrome_limit == 0
    assert "youtube" not in {
        row["resource_id"] for row in _connect(db).execute("SELECT resource_id FROM rule_resources")
    }


def test_stale_rule_match_ids_table_is_replaced(tmp_path):
    db = tmp_path / "screen_time.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE resources (
            id INTEGER PRIMARY KEY,
            resource_type TEXT NOT NULL,
            resource_id TEXT NOT NULL
        );
        CREATE TABLE daily_usage (
            id INTEGER PRIMARY KEY,
            usage_date TEXT NOT NULL
        );
        CREATE TABLE rule_match_ids (
            id INTEGER PRIMARY KEY,
            resource_id TEXT
        );
        CREATE TABLE rule_resources (
            id INTEGER PRIMARY KEY,
            resource_type TEXT,
            resource_id TEXT
        );
        """
    )
    conn.close()
    SqliteUsageStore(db)
    conn = _connect(db)
    names = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'rule_%'")
    }
    cols = [row[1] for row in conn.execute("PRAGMA table_info(rule_resources)")]
    conn.close()
    assert "rule_match_ids" not in names
    assert "rule_resource_match_ids" in names
    assert "rule_screen_time_settings" in names
    assert cols[0] == "resource_id"
