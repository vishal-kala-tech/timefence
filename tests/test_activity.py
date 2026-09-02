from timefence.activity import find_resource_by_bundle_id, find_resource_for_activity, uses_app_capture
from timefence.models.activity import KIND_APP, KIND_WEBSITE, Activity
from tests.helpers import make_resource

ROBLOX = "com.roblox.RobloxPlayer"
DISCORD = "com.hnc.Discord"

RESOURCES = {
    "roblox": make_resource(
        enabled=True,
        type="app",
        display_name="Roblox",
        bundle_ids=[ROBLOX, "com.roblox.Roblox"],
    ),
    "discord": make_resource(
        enabled=True,
        type="app",
        display_name="Discord",
        bundle_ids=[DISCORD],
    ),
    "youtube": make_resource(
        enabled=True,
        type="website",
        url_contains=["youtube.com/watch"],
    ),
}


def test_bundle_id_matches_configured_roblox():
    match = find_resource_by_bundle_id(RESOURCES, ROBLOX)
    assert match is not None
    assert match[0] == "roblox"


def test_bundle_id_match_is_case_insensitive():
    match = find_resource_by_bundle_id(RESOURCES, "COM.ROBLOX.ROBLOXPLAYER")
    assert match[0] == "roblox"


def test_unknown_bundle_id_returns_none():
    assert find_resource_by_bundle_id(RESOURCES, "com.google.Chrome") is None
    assert find_resource_by_bundle_id(RESOURCES, "") is None
    assert find_resource_by_bundle_id(RESOURCES, None) is None


def test_disabled_resource_is_not_matched():
    resources = {
        "roblox": make_resource(enabled=False, type="app", bundle_ids=[ROBLOX]),
        "discord": make_resource(enabled=True, type="app", bundle_ids=[DISCORD]),
    }
    assert find_resource_by_bundle_id(resources, ROBLOX) is None
    assert find_resource_by_bundle_id(resources, DISCORD)[0] == "discord"


def test_activity_dispatch_matches_app_and_future_website():
    app = Activity(kind=KIND_APP, identifier=ROBLOX, display_name="Roblox", pid=11)
    assert find_resource_for_activity(RESOURCES, app)[0] == "roblox"
    web = Activity(kind=KIND_WEBSITE, identifier="https://www.youtube.com/watch?v=abc")
    assert find_resource_for_activity(RESOURCES, web)[0] == "youtube"


def test_uses_app_capture_for_bundle_and_type_app():
    assert uses_app_capture(RESOURCES["roblox"]) is True
    assert uses_app_capture(RESOURCES["youtube"]) is False
    assert uses_app_capture(make_resource(type="app")) is True
    assert uses_app_capture(make_resource()) is False


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
