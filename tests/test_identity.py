from timefence.identity import (
    RESOURCE_TYPE_APP,
    RESOURCE_TYPE_VIDEO_CATEGORY,
    RESOURCE_TYPE_WEBSITE,
    YOUTUBE_SHORTS_RESOURCE_ID,
    YOUTUBE_VIDEOS_RESOURCE_ID,
    classify_youtube,
    default_display_name,
    website_id,
)
from timefence.tracking import SqliteUsageStore


def test_terminal_display_name():
    assert default_display_name(RESOURCE_TYPE_APP, "com.apple.Terminal") == "Terminal"


def test_chrome_display_name():
    assert default_display_name(RESOURCE_TYPE_APP, "com.google.Chrome") == "Google Chrome"


def test_github_website_id_and_display():
    assert website_id("https://www.github.com/cursor") == "github.com"
    assert default_display_name(RESOURCE_TYPE_WEBSITE, "github.com") == "GitHub"


def test_youtube_website_id_and_display():
    assert website_id("https://www.youtube.com/watch?v=abc") == "youtube.com"
    assert default_display_name(RESOURCE_TYPE_WEBSITE, "youtube.com") == "YouTube"


def test_youtube_watch_classifies_as_videos():
    assert classify_youtube("https://www.youtube.com/watch?v=abc") == YOUTUBE_VIDEOS_RESOURCE_ID


def test_youtube_shorts_classifies_as_shorts():
    assert classify_youtube("https://www.youtube.com/shorts/xyz") == YOUTUBE_SHORTS_RESOURCE_ID


def test_screen_time_is_app_layer_only(tmp_path):
    store = SqliteUsageStore(tmp_path / "screen_time.sqlite")
    stamp = "2026-09-02T16:00:00"
    day = "2026-09-02"
    store.add_active_seconds(day, RESOURCE_TYPE_APP, "com.google.Chrome", 600, stamp)
    store.add_active_seconds(day, RESOURCE_TYPE_WEBSITE, "youtube.com", 600, stamp)
    store.add_active_seconds(day, RESOURCE_TYPE_VIDEO_CATEGORY, YOUTUBE_VIDEOS_RESOURCE_ID, 600, stamp)
    screen_time = sum(
        row.total_active_seconds for row in store.get_all_daily(day, resource_type=RESOURCE_TYPE_APP)
    )
    assert screen_time == 600
    assert store.get_daily(day, RESOURCE_TYPE_WEBSITE, "youtube.com").total_active_seconds == 600
    assert (
        store.get_daily(day, RESOURCE_TYPE_VIDEO_CATEGORY, YOUTUBE_VIDEOS_RESOURCE_ID).total_active_seconds
        == 600
    )


def test_every_table_has_autoincrement_id(tmp_path):
    import sqlite3

    path = tmp_path / "screen_time.sqlite"
    store = SqliteUsageStore(path)
    store.ensure_resource(RESOURCE_TYPE_APP, "com.google.Chrome", display_name="Google Chrome", updated_at="t")
    store.ensure_resource(RESOURCE_TYPE_WEBSITE, "github.com", display_name="GitHub", updated_at="t")
    chrome = store.get_resource(RESOURCE_TYPE_APP, "com.google.Chrome")
    github = store.get_resource(RESOURCE_TYPE_WEBSITE, "github.com")
    assert chrome["id"] == 1
    assert github["id"] == 2
    first = store.add_active_seconds("2026-09-02", RESOURCE_TYPE_APP, "com.google.Chrome", 10, "t")
    second = store.add_active_seconds("2026-09-02", RESOURCE_TYPE_WEBSITE, "github.com", 10, "t")
    assert first == 10
    assert second == 10
    assert store.get_daily("2026-09-02", RESOURCE_TYPE_APP, "com.google.Chrome").id == 1
    assert store.get_daily("2026-09-02", RESOURCE_TYPE_WEBSITE, "github.com").id == 2
    conn = sqlite3.connect(path)
    tables = [
        "resources",
        "daily_usage",
        "usage_sessions",
        "warning_state",
        "window_usage",
        "browse_visits",
        "watch_history",
    ]
    for table in tables:
        cols = {row[1]: row for row in conn.execute(f"PRAGMA table_info({table})")}
        assert cols["id"][5] == 1
    conn.close()
