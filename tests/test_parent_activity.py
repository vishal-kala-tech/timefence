from datetime import date, datetime, timedelta, timezone

from timefence import browse
from timefence.parent_activity import compact_clock, day_report, parse_report_date
from timefence.status_server import ensure, stop, url
from timefence.tracking import SqliteUsageStore
from timefence.usage import add_usage
from tests.helpers import make_config, make_day_policy, make_resource, make_window, write_rules
from tests.test_parent import _json, _opener


WHEN = datetime(2024, 1, 15, 16, 30, 0)
LATER = datetime(2024, 1, 15, 16, 45, 0)


def _seed(app_dir):
    write_rules(
        app_dir,
        make_config(
            resources={
                "chrome": make_resource(display_name="Chrome", default=make_day_policy(daily_limit_minutes=0)),
                "youtube": make_resource(display_name="YouTube", default=make_day_policy(daily_limit_minutes=30)),
            }
        ),
    )
    store = SqliteUsageStore(app_dir / "state" / "screen_time.sqlite")
    store.add_active_seconds("2024-01-15", "chrome", 900, WHEN.isoformat())
    sid = store.start_session("chrome", WHEN.isoformat(), identifier="com.google.Chrome")
    store.end_session(sid, LATER.isoformat(), 900)
    add_usage(
        app_dir / "state",
        "youtube",
        45,
        window_id="all_day",
        now=WHEN,
        video={
            "id": "aaaaaaaaaaa",
            "title": "Clip",
            "channel": "Channel A",
            "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
        },
    )
    browse.note_visit(
        app_dir / "state",
        {
            "host": "www.youtube.com",
            "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
            "title": "Clip",
            "browser": "chrome",
        },
        45,
        now=WHEN,
    )


def test_parse_report_date_defaults_and_clamps():
    today = date(2024, 1, 15)
    assert parse_report_date(None, now=today) == today
    assert parse_report_date("2024-01-14", now=today) == date(2024, 1, 14)
    assert parse_report_date("2024-01-20", now=today) == today
    try:
        parse_report_date("nope", now=today)
    except ValueError as exc:
        assert "YYYY-MM-DD" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_day_report_summarizes_apps_sites_and_videos(app_dir):
    _seed(app_dir)
    report = day_report(app_dir, date="2024-01-15", now=WHEN)
    assert report["date"] == "2024-01-15"
    assert report["is_today"] is True
    assert report["prev_date"] == "2024-01-14"
    assert report["next_date"] is None
    assert report["has_data"] is True
    assert report["summary"]["app_seconds"] == 900
    chrome = report["apps"][0]
    assert chrome["label"] == "Chrome"
    assert chrome["sessions"][0]["seconds"] == 900
    assert report["sites"]["hosts"][0]["host"] == "youtube.com"
    assert report["videos"][0]["items"][0]["title"] == "Clip"
    assert report["summary"]["video_count"] == 1
    assert report["summary"]["app_compact"] == "15m"
    assert report["short_label"]
    assert "Chrome" in report["daily_summary"]
    assert report["current"] is None
    youtube_limit = next(row for row in report["limits"] if row["id"] == "youtube")
    assert youtube_limit["limit_seconds"] == 30 * 60
    assert youtube_limit["status"] in ("ok", "warning", "blocked")
    assert report["next_rule"] is None
    empty = day_report(app_dir, date="2024-01-14", now=WHEN)
    assert empty["has_data"] is False
    assert empty["next_date"] == "2024-01-15"


def test_activity_api_requires_pin(app_dir):
    _seed(app_dir)
    httpd, port = ensure(app_dir, 0)
    try:
        base = url(port).rstrip("/")
        anon = _opener()
        code, payload = _json(anon, base + "/api/parent/activity")
        assert code == 401
        code, payload = _json(anon, base + "/api/pin", "POST", {"pin": "2468"})
        assert code == 200
        code, report = _json(anon, base + "/api/parent/activity?date=2024-01-15")
        assert code == 200
        assert report["date"] == "2024-01-15"
        assert report["apps"][0]["id"] == "chrome"
        assert "daily_summary" in report
        assert "limits" in report
        assert "current" in report
        code, payload = _json(anon, base + "/api/parent/activity?date=bad")
        assert code == 400
    finally:
        stop()


def test_compact_clock_formats_short_durations():
    assert compact_clock(0) == "0s"
    assert compact_clock(50) == "50s"
    assert compact_clock(126) == "2m 6s"
    assert compact_clock(41 * 60) == "41m"
    assert compact_clock(2 * 3600 + 6 * 60) == "2h 06m"


def test_open_session_is_current_activity(app_dir):
    write_rules(
        app_dir,
        make_config(
            resources={
                "chrome": make_resource(display_name="Chrome", default=make_day_policy(daily_limit_minutes=0)),
            }
        ),
    )
    store = SqliteUsageStore(app_dir / "state" / "screen_time.sqlite")
    store.add_active_seconds("2024-01-15", "chrome", 480, WHEN.isoformat())
    store.start_session("chrome", WHEN.isoformat(), identifier="com.google.Chrome")
    report = day_report(app_dir, date="2024-01-15", now=LATER)
    assert report["current"]["label"] == "Chrome"
    assert report["current"]["seconds"] >= 900


def test_current_activity_accepts_timezone_aware_session_start(app_dir):
    write_rules(
        app_dir,
        make_config(
            resources={
                "chrome": make_resource(display_name="Chrome", default=make_day_policy(daily_limit_minutes=0)),
            }
        ),
    )
    started = datetime(2024, 1, 15, 16, 30, tzinfo=timezone(timedelta(hours=-5)))
    later = datetime(2024, 1, 15, 16, 45, tzinfo=timezone(timedelta(hours=-5)))
    store = SqliteUsageStore(app_dir / "state" / "screen_time.sqlite")
    store.add_active_seconds("2024-01-15", "chrome", 480, started.isoformat())
    store.start_session("chrome", started.isoformat(), identifier="com.google.Chrome")
    report = day_report(app_dir, date="2024-01-15", now=later)
    assert report["current"]["label"] == "Chrome"
    assert report["current"]["seconds"] >= 900


def test_next_rule_uses_upcoming_window(app_dir):
    write_rules(
        app_dir,
        make_config(
            resources={
                "roblox": make_resource(
                    display_name="Roblox",
                    default=make_day_policy(
                        daily_limit_minutes=30,
                        allowed_windows=[make_window("evening", "17:00", "19:00", limit_minutes=30)],
                    ),
                )
            }
        ),
    )
    report = day_report(app_dir, date="2024-01-15", now=WHEN)
    assert report["next_rule"]["title"] == "Roblox available"
    assert "5:00 PM" in report["next_rule"]["detail"]
