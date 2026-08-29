from datetime import datetime, timedelta

from timefence.grants import (
    BONUS_WINDOW_ID,
    active_grant,
    apply_grant,
    clear_grant,
    effective_daily_limit,
    find_resource,
    grant_expiry,
    grant_from_config,
    grant_summary,
    load_grant,
    plan_grant,
)
from timefence.policy import evaluate
from timefence.usage import add_usage
from tests.helpers import make_config, make_day_policy, make_resource, make_window, write_rules

MONDAY_NOON = datetime(2024, 1, 15, 12, 0)
MONDAY_AFTERNOON = datetime(2024, 1, 15, 16, 30)
POLICY = make_day_policy(
    daily_limit_minutes=45,
    allowed_windows=[
        make_window("after_school", "16:00", "18:00", limit_minutes=30),
        make_window("evening", "19:00", "20:30", limit_minutes=30),
    ],
)


def test_grant_expiry_stops_at_midnight():
    now = datetime(2024, 1, 15, 23, 50)
    assert grant_expiry(now, 15) == datetime(2024, 1, 16, 0, 0)


def test_expired_grant_is_inactive():
    grant = {"expires_at": "2024-01-15T16:00:00", "extra_daily_seconds": 900}
    assert active_grant(grant, now=datetime(2024, 1, 15, 16, 0)) is None
    assert active_grant(grant, now=datetime(2024, 1, 15, 15, 59)) is grant


def test_plan_grant_outside_window_sets_allow_until():
    planned = plan_grant(POLICY, {"total_usage_seconds": 0, "windows": {}}, 15, now=MONDAY_NOON)
    assert planned["reason"] == "outside_window"
    assert planned["allow_until"] == "2024-01-15T12:15:00"
    assert planned["extra_daily_seconds"] == 15 * 60
    decision = evaluate(POLICY, {"total_usage_seconds": 0, "windows": {}}, now=MONDAY_NOON, grant=planned)
    assert decision.allowed is True
    assert decision.window_id == BONUS_WINDOW_ID


def test_plan_grant_daily_limit_adds_budget(app_dir):
    state = {"total_usage_seconds": 45 * 60, "windows": {"after_school": {"usage_seconds": 20 * 60}}}
    planned = plan_grant(POLICY, state, 10, now=MONDAY_AFTERNOON)
    assert planned["reason"] == "daily_limit"
    assert planned["extra_daily_seconds"] == 600
    blocked = evaluate(POLICY, state, now=MONDAY_AFTERNOON)
    assert blocked.allowed is False
    allowed = evaluate(POLICY, state, now=MONDAY_AFTERNOON, grant=planned)
    assert allowed.allowed is True
    assert effective_daily_limit(POLICY, planned, now=MONDAY_AFTERNOON) == 55 * 60


def test_plan_grant_window_limit_adds_window_and_daily_if_needed():
    state = {
        "total_usage_seconds": 30 * 60,
        "windows": {"after_school": {"usage_seconds": 30 * 60}},
    }
    planned = plan_grant(POLICY, state, 10, now=MONDAY_AFTERNOON)
    assert planned["reason"] == "window_limit"
    assert planned["extra_windows"]["after_school"] == 600
    assert planned["extra_daily_seconds"] == 600
    assert evaluate(POLICY, state, now=MONDAY_AFTERNOON, grant=planned).allowed is True


def test_apply_grant_persists_and_expires(app_dir):
    grant = apply_grant(app_dir / "state", "youtube", POLICY, 15, now=MONDAY_NOON)
    loaded = load_grant(app_dir / "state", "youtube", now=MONDAY_NOON + timedelta(minutes=5))
    assert loaded["expires_at"] == grant["expires_at"]
    assert load_grant(app_dir / "state", "youtube", now=MONDAY_NOON + timedelta(minutes=16)) is None
    assert load_grant(app_dir / "state", "youtube", now=datetime(2024, 1, 16, 10, 0)) is None


def test_apply_grant_merges_extra_time(app_dir):
    apply_grant(app_dir / "state", "youtube", POLICY, 10, now=MONDAY_NOON)
    merged = apply_grant(app_dir / "state", "youtube", POLICY, 10, now=MONDAY_NOON + timedelta(minutes=2))
    assert merged["extra_daily_seconds"] == 20 * 60
    assert merged["expires_at"] == "2024-01-15T12:12:00"


def test_clear_grant(app_dir):
    apply_grant(app_dir / "state", "youtube", POLICY, 15, now=MONDAY_NOON)
    clear_grant(app_dir / "state", "youtube", now=MONDAY_NOON)
    assert load_grant(app_dir / "state", "youtube", now=MONDAY_NOON) is None


def test_find_resource_by_display_name():
    cfg = make_config(
        resources={"youtube_shorts": make_resource(display_name="YouTube Shorts")}
    )
    name, resource = find_resource(cfg, "youtube shorts")
    assert name == "youtube_shorts"
    assert resource["display_name"] == "YouTube Shorts"


def test_grant_from_config(app_dir):
    write_rules(
        app_dir,
        make_config(resources={"youtube": make_resource(display_name="YouTube", default=POLICY)}),
    )
    from timefence.config import load_config

    cfg = load_config(app_dir / "config/rules.json")
    name, grant = grant_from_config(cfg, app_dir / "state", "YouTube", 15, now=MONDAY_NOON)
    assert name == "youtube"
    assert "Bonus until" in grant_summary(grant, now=MONDAY_NOON)


def test_grant_summary_none_when_expired():
    assert grant_summary({"expires_at": "2024-01-15T12:00:00"}, now=MONDAY_AFTERNOON) is None
