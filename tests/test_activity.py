from timefence.activity import (
    find_resource_by_bundle_id,
    find_resource_for_activity,
    usage_id_for_activity,
    uses_app_capture,
)
from timefence.identity import RESOURCE_TYPE_APP, RESOURCE_TYPE_WEBSITE, resource_id_of
from timefence.models.activity import KIND_APP, KIND_WEBSITE, Activity
from tests.helpers import make_resource

ROBLOX = "com.roblox.RobloxPlayer"
DISCORD = "com.hnc.Discord"

RESOURCES = [
    make_resource(
        resource_type=RESOURCE_TYPE_APP,
        resource_id=ROBLOX,
        display_name="Roblox",
        match_ids=[ROBLOX, "com.roblox.Roblox"],
    ),
    make_resource(
        resource_type=RESOURCE_TYPE_APP,
        resource_id=DISCORD,
        display_name="Discord",
        match_ids=[DISCORD],
    ),
    make_resource(
        resource_type=RESOURCE_TYPE_WEBSITE,
        resource_id="youtube.com",
        display_name="YouTube",
        url_contains=["youtube.com/watch"],
    ),
]


def test_bundle_id_matches_configured_roblox():
    match = find_resource_by_bundle_id(RESOURCES, ROBLOX)
    assert match is not None
    assert resource_id_of(match) == ROBLOX


def test_bundle_id_match_is_case_insensitive():
    match = find_resource_by_bundle_id(RESOURCES, "COM.ROBLOX.ROBLOXPLAYER")
    assert resource_id_of(match) == ROBLOX


def test_unknown_bundle_id_returns_none():
    assert find_resource_by_bundle_id(RESOURCES, "com.google.Chrome") is None
    assert find_resource_by_bundle_id(RESOURCES, "") is None
    assert find_resource_by_bundle_id(RESOURCES, None) is None


def test_disabled_resource_is_not_matched():
    resources = [
        make_resource(enabled=False, resource_type=RESOURCE_TYPE_APP, resource_id=ROBLOX, match_ids=[ROBLOX]),
        make_resource(enabled=True, resource_type=RESOURCE_TYPE_APP, resource_id=DISCORD, match_ids=[DISCORD]),
    ]
    assert find_resource_by_bundle_id(resources, ROBLOX) is None
    assert resource_id_of(find_resource_by_bundle_id(resources, DISCORD)) == DISCORD


def test_activity_dispatch_matches_app_and_future_website():
    app = Activity(kind=KIND_APP, identifier=ROBLOX, display_name="Roblox", pid=11)
    assert resource_id_of(find_resource_for_activity(RESOURCES, app)) == ROBLOX
    web = Activity(kind=KIND_WEBSITE, identifier="https://www.youtube.com/watch?v=abc")
    assert resource_id_of(find_resource_for_activity(RESOURCES, web)) == "youtube.com"


def test_usage_id_uses_canonical_bundle_or_observed_id():
    listed = Activity(kind=KIND_APP, identifier=ROBLOX, display_name="Roblox")
    other = Activity(kind=KIND_APP, identifier="com.apple.finder", display_name="Finder")
    web = Activity(kind=KIND_WEBSITE, identifier="https://example.com/")
    assert usage_id_for_activity(RESOURCES, listed) == ROBLOX
    assert usage_id_for_activity(RESOURCES, other) == "com.apple.finder"
    assert usage_id_for_activity(RESOURCES, web) is None


def test_uses_app_capture_for_bundle_and_type_app():
    assert uses_app_capture(RESOURCES[0]) is True
    assert uses_app_capture(RESOURCES[2]) is False
    assert uses_app_capture(make_resource(resource_type=RESOURCE_TYPE_APP)) is True
    assert uses_app_capture(make_resource(resource_type=RESOURCE_TYPE_WEBSITE, resource_id="github.com")) is False


def test_monitor_treats_loginwindow_as_locked():
    from datetime import datetime

    from timefence.activity.macos_activity_monitor import MacOSActivityMonitor
    from timefence.models.activity import FrontmostApp

    monitor = MacOSActivityMonitor(
        frontmost_fn=lambda: FrontmostApp("loginwindow", "com.apple.loginwindow", 1),
        idle_fn=lambda: 0.0,
        locked_fn=lambda: False,
    )
    snap = monitor.capture(now=datetime(2026, 8, 30, 16, 0, 0))
    assert snap.screen_locked is True
    assert snap.frontmost.bundle_id == "com.apple.loginwindow"
