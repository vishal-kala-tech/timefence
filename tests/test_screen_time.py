import logging
from datetime import datetime, timedelta

from timefence.identity import RESOURCE_TYPE_APP, RESOURCE_TYPE_WEBSITE
from timefence.models.activity import FrontmostApp, Observation
from timefence.tracking import SqliteUsageStore, UsageTracker
from timefence.tracking.usage_tracker import ScreenTimeSettings
from tests.helpers import make_day_policy, make_resource

ROBLOX_BUNDLE = "com.roblox.RobloxPlayer"
CHROME_BUNDLE = "com.google.Chrome"
DISCORD_BUNDLE = "com.hnc.Discord"
FINDER_BUNDLE = "com.apple.finder"
SETTINGS = ScreenTimeSettings(
    enabled=True,
    poll_interval_seconds=10,
    idle_threshold_seconds=120,
    max_countable_interval_seconds=30,
)
START = datetime(2026, 8, 30, 16, 1, 20)


def roblox_resource():
    return make_resource(
        enabled=True,
        resource_type=RESOURCE_TYPE_APP,
        resource_id=ROBLOX_BUNDLE,
        display_name="Roblox",
        match_ids=[ROBLOX_BUNDLE, "com.roblox.Roblox"],
        default=make_day_policy(daily_limit_minutes=30),
    )


def discord_resource():
    return make_resource(
        enabled=True,
        resource_type=RESOURCE_TYPE_APP,
        resource_id=DISCORD_BUNDLE,
        display_name="Discord",
        match_ids=[DISCORD_BUNDLE],
        weekday=make_day_policy(daily_limit_minutes=30),
    )


def resources():
    return [roblox_resource(), discord_resource()]


def observation(now, bundle_id=ROBLOX_BUNDLE, app_name="Roblox", pid=12345, idle=0, locked=False):
    front = None
    if bundle_id:
        front = FrontmostApp(app_name=app_name, bundle_id=bundle_id, pid=pid)
    return Observation(timestamp=now, idle_seconds=idle, screen_locked=locked, frontmost=front)


def tracker(tmp_path):
    store = SqliteUsageStore(tmp_path / "screen_time.sqlite")
    return UsageTracker(store)


def test_foreground_transition_closes_roblox_session(tmp_path):
    tr = tracker(tmp_path)
    cfg = resources()
    t0 = START
    t1 = t0 + timedelta(seconds=10)
    t2 = t1 + timedelta(seconds=10)
    t3 = t2 + timedelta(seconds=10)

    tr.apply(observation(t0, ROBLOX_BUNDLE), cfg, SETTINGS)
    tr.apply(observation(t1, ROBLOX_BUNDLE), cfg, SETTINGS)
    assert tr.get_current_session(ROBLOX_BUNDLE) is not None

    tr.apply(observation(t2, CHROME_BUNDLE, app_name="Google Chrome"), cfg, SETTINGS)
    tr.apply(observation(t3, CHROME_BUNDLE, app_name="Google Chrome"), cfg, SETTINGS)
    assert tr.get_current_session(ROBLOX_BUNDLE) is None
    assert tr.get_current_activity()["resource_id"] == CHROME_BUNDLE
    usage = tr.get_today_usage(ROBLOX_BUNDLE, resource=roblox_resource(), now=t3)
    assert usage.used_seconds == 20
    assert usage.currently_active is False


def test_idle_stops_accumulating_usage(tmp_path, caplog):
    tr = tracker(tmp_path)
    cfg = resources()
    t0 = START
    t1 = t0 + timedelta(seconds=10)
    t2 = t1 + timedelta(seconds=10)

    tr.apply(observation(t0), cfg, SETTINGS)
    tr.apply(observation(t1), cfg, SETTINGS)
    caplog.set_level(logging.INFO)
    tr.apply(observation(t2, idle=145), cfg, SETTINGS)

    assert tr.get_today_usage(ROBLOX_BUNDLE, now=t2).used_seconds == 10
    assert tr.get_current_session(ROBLOX_BUNDLE) is None
    assert any("SCREEN_TIME_IDLE" in r.getMessage() for r in caplog.records)


def test_idle_return_starts_a_new_session(tmp_path):
    tr = tracker(tmp_path)
    cfg = resources()
    t0 = START
    t1 = t0 + timedelta(seconds=10)
    t2 = t1 + timedelta(seconds=10)
    t3 = t2 + timedelta(seconds=10)

    tr.apply(observation(t0), cfg, SETTINGS)
    first = tr.get_current_session(ROBLOX_BUNDLE)
    tr.apply(observation(t1, idle=200), cfg, SETTINGS)
    assert tr.get_current_session(ROBLOX_BUNDLE) is None

    tr.apply(observation(t2), cfg, SETTINGS)
    second = tr.get_current_session(ROBLOX_BUNDLE)
    assert second is not None
    assert second.started_at != first.started_at

    tr.apply(observation(t3), cfg, SETTINGS)
    assert tr.get_today_usage(ROBLOX_BUNDLE, now=t3).used_seconds == 10
    assert tr.get_current_session(ROBLOX_BUNDLE).duration_seconds == 10


def test_poll_timing_counts_elapsed_seconds(tmp_path):
    tr = tracker(tmp_path)
    cfg = resources()
    t0 = START
    t1 = t0 + timedelta(seconds=10)
    tr.apply(observation(t0), cfg, SETTINGS)
    tr.apply(observation(t1), cfg, SETTINGS)
    usage = tr.get_today_usage(ROBLOX_BUNDLE, resource=roblox_resource(), now=t1)
    assert usage.used_seconds == 10
    assert usage.used_minutes == 0
    assert usage.limit_seconds == 30 * 60
    assert usage.remaining_seconds == 30 * 60 - 10
    assert usage.currently_active is True
    assert usage.current_session_seconds == 10


def test_large_polling_gap_is_not_counted(tmp_path):
    tr = tracker(tmp_path)
    cfg = resources()
    t0 = datetime(2026, 8, 30, 10, 0, 0)
    t1 = datetime(2026, 8, 30, 10, 10, 0)
    tr.apply(observation(t0), cfg, SETTINGS)
    result = tr.apply(observation(t1), cfg, SETTINGS)
    assert result.interrupted is True
    assert result.increment_seconds == 0
    assert tr.get_today_usage(ROBLOX_BUNDLE, now=t1).used_seconds == 0
    assert tr.get_current_session(ROBLOX_BUNDLE) is not None


def test_background_app_does_not_count(tmp_path):
    tr = tracker(tmp_path)
    cfg = resources()
    t0 = START
    t1 = t0 + timedelta(seconds=10)
    t2 = t1 + timedelta(seconds=10)
    t3 = t2 + timedelta(seconds=10)
    tr.apply(observation(t0, ROBLOX_BUNDLE), cfg, SETTINGS)
    tr.apply(observation(t1, ROBLOX_BUNDLE), cfg, SETTINGS)
    tr.apply(observation(t2, CHROME_BUNDLE, app_name="Google Chrome"), cfg, SETTINGS)
    tr.apply(observation(t3, CHROME_BUNDLE, app_name="Google Chrome"), cfg, SETTINGS)
    assert tr.get_today_usage(ROBLOX_BUNDLE, now=t3).used_seconds == 20
    assert tr.get_today_usage(DISCORD_BUNDLE, now=t3).used_seconds == 0
    assert tr.get_today_usage(CHROME_BUNDLE, now=t3).used_seconds == 10


def test_never_counts_two_resources_at_once(tmp_path):
    tr = tracker(tmp_path)
    cfg = resources()
    t0 = START
    t1 = t0 + timedelta(seconds=10)
    t2 = t1 + timedelta(seconds=10)
    tr.apply(observation(t0, ROBLOX_BUNDLE), cfg, SETTINGS)
    tr.apply(observation(t1, DISCORD_BUNDLE, app_name="Discord"), cfg, SETTINGS)
    tr.apply(observation(t2, DISCORD_BUNDLE, app_name="Discord"), cfg, SETTINGS)
    assert tr.get_today_usage(ROBLOX_BUNDLE, now=t2).used_seconds == 10
    assert tr.get_today_usage(DISCORD_BUNDLE, now=t2).used_seconds == 10
    assert tr.get_current_activity()["resource_id"] == DISCORD_BUNDLE


def test_restart_preserves_daily_usage(tmp_path):
    path = tmp_path / "screen_time.sqlite"
    cfg = resources()
    t0 = START
    t1 = t0 + timedelta(seconds=10)
    t2 = t1 + timedelta(seconds=10)

    first = UsageTracker(SqliteUsageStore(path))
    first.apply(observation(t0), cfg, SETTINGS)
    first.apply(observation(t1), cfg, SETTINGS)
    first.apply(observation(t2), cfg, SETTINGS)
    first.close(now=t2)
    assert first.get_today_usage(ROBLOX_BUNDLE, now=t2).used_seconds == 20

    second = UsageTracker(SqliteUsageStore(path))
    second.close_orphaned_sessions(now=t2)
    usage = second.get_today_usage(ROBLOX_BUNDLE, resource=roblox_resource(), now=t2)
    assert usage.used_seconds == 20
    assert usage.currently_active is False
    assert second.get_current_session(ROBLOX_BUNDLE) is None


def test_day_rollover_does_not_count_yesterday_toward_today(tmp_path):
    tr = tracker(tmp_path)
    cfg = resources()
    yesterday = datetime(2026, 8, 29, 23, 59, 50)
    today = datetime(2026, 8, 30, 0, 0, 5)
    later = today + timedelta(seconds=10)

    tr.apply(observation(yesterday), cfg, SETTINGS)
    tr.apply(observation(today), cfg, SETTINGS)
    assert tr.store.get_daily("2026-08-29", RESOURCE_TYPE_APP, ROBLOX_BUNDLE).total_active_seconds == 10
    assert tr.get_today_usage(ROBLOX_BUNDLE, now=today).used_seconds == 5

    tr.apply(observation(later), cfg, SETTINGS)
    assert tr.get_today_usage(ROBLOX_BUNDLE, now=later).used_seconds == 15
    assert tr.store.get_daily("2026-08-29", RESOURCE_TYPE_APP, ROBLOX_BUNDLE).total_active_seconds == 10
    today_sessions = tr.store.get_sessions_on_date("2026-08-30")
    assert today_sessions
    assert today_sessions[-1].identifier == ROBLOX_BUNDLE


def test_screen_lock_ends_session_without_counting(tmp_path):
    tr = tracker(tmp_path)
    cfg = resources()
    t0 = START
    t1 = t0 + timedelta(seconds=10)
    t2 = t1 + timedelta(seconds=10)
    tr.apply(observation(t0), cfg, SETTINGS)
    tr.apply(observation(t1), cfg, SETTINGS)
    tr.apply(observation(t2, locked=True), cfg, SETTINGS)
    assert tr.get_today_usage(ROBLOX_BUNDLE, now=t2).used_seconds == 10
    assert tr.get_current_session(ROBLOX_BUNDLE) is None


def test_query_helpers_and_snapshot(tmp_path):
    tr = tracker(tmp_path)
    cfg = resources()
    t0 = START
    t1 = t0 + timedelta(seconds=10)
    tr.apply(observation(t0), cfg, SETTINGS)
    tr.apply(observation(t1), cfg, SETTINGS)
    usage = tr.get_today_usage(ROBLOX_BUNDLE, resource=roblox_resource(), now=t1)
    assert usage.to_dict()["used_seconds"] == 10
    assert tr.get_remaining_seconds(ROBLOX_BUNDLE, resource=roblox_resource(), now=t1) == 30 * 60 - 10
    assert tr.get_current_activity()["resource_id"] == ROBLOX_BUNDLE
    snap = tr.snapshot(ROBLOX_BUNDLE, now=t1)
    assert snap.is_currently_active is True
    assert snap.total_active_seconds == 10
    assert len(tr.get_all_today_usage(resources=cfg, now=t1)) >= 1


def test_limit_warning_recorded_once(tmp_path):
    store = SqliteUsageStore(tmp_path / "screen_time.sqlite")
    assert store.record_warning("2026-08-30", RESOURCE_TYPE_APP, ROBLOX_BUNDLE, "limit_reached") is True
    assert store.record_warning("2026-08-30", RESOURCE_TYPE_APP, ROBLOX_BUNDLE, "limit_reached") is False
    assert store.has_warning("2026-08-30", RESOURCE_TYPE_APP, ROBLOX_BUNDLE, "limit_reached") is True
    assert store.has_warning("2026-08-31", RESOURCE_TYPE_APP, ROBLOX_BUNDLE, "limit_reached") is False


def test_window_usage_accumulates_per_window(tmp_path):
    store = SqliteUsageStore(tmp_path / "screen_time.sqlite")
    assert store.add_window_seconds("2026-08-30", RESOURCE_TYPE_APP, ROBLOX_BUNDLE, "after_school", 20, START.isoformat()) == 20
    assert store.add_window_seconds("2026-08-30", RESOURCE_TYPE_APP, ROBLOX_BUNDLE, "after_school", 10, START.isoformat()) == 30
    assert store.add_window_seconds("2026-08-30", RESOURCE_TYPE_APP, ROBLOX_BUNDLE, "evening", 15, START.isoformat()) == 15
    assert store.get_windows("2026-08-30", RESOURCE_TYPE_APP, ROBLOX_BUNDLE) == {"after_school": 30, "evening": 15}
    assert store.get_windows("2026-08-31", RESOURCE_TYPE_APP, ROBLOX_BUNDLE) == {}


def test_website_activity_can_feed_the_same_tracker(tmp_path):
    from timefence.models.activity import KIND_WEBSITE, Activity

    tr = tracker(tmp_path)
    cfg = resources() + [
        make_resource(
            enabled=True,
            resource_type=RESOURCE_TYPE_WEBSITE,
            resource_id="youtube.com",
            display_name="YouTube",
            url_contains=["youtube.com/watch"],
            default=make_day_policy(daily_limit_minutes=30),
        )
    ]
    t0 = START
    t1 = t0 + timedelta(seconds=10)
    activity = Activity(kind=KIND_WEBSITE, identifier="https://www.youtube.com/watch?v=abc")
    tr.apply(Observation(timestamp=t0, idle_seconds=0, activity=activity), cfg, SETTINGS)
    tr.apply(Observation(timestamp=t1, idle_seconds=0, activity=activity), cfg, SETTINGS)
    assert tr.get_today_usage("youtube.com", resource_type=RESOURCE_TYPE_WEBSITE, now=t1).used_seconds == 10
    assert tr.get_today_usage(ROBLOX_BUNDLE, now=t1).used_seconds == 0


def test_unlisted_foreground_app_is_recorded_under_bundle_id(tmp_path):
    tr = tracker(tmp_path)
    cfg = resources()
    t0 = START
    t1 = t0 + timedelta(seconds=10)
    t2 = t1 + timedelta(seconds=10)
    tr.apply(observation(t0, FINDER_BUNDLE, app_name="Finder"), cfg, SETTINGS)
    tr.apply(observation(t1, FINDER_BUNDLE, app_name="Finder"), cfg, SETTINGS)
    tr.apply(observation(t2, FINDER_BUNDLE, app_name="Finder"), cfg, SETTINGS)
    assert tr.get_today_usage(FINDER_BUNDLE, now=t2).used_seconds == 20
    assert tr.get_current_activity()["resource_id"] == FINDER_BUNDLE
    assert tr.get_current_activity()["identifier"] == FINDER_BUNDLE
    names = {row["resource_id"]: row["display_name"] for row in tr.store.list_resources()}
    assert names[FINDER_BUNDLE] == "Finder"
    assert tr.get_today_usage(ROBLOX_BUNDLE, now=t2).used_seconds == 0
