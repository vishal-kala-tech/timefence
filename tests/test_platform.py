from timefence.activity.matching import app_ids_for, find_resource_by_app_id, uses_app_capture
from timefence.platform import create_activity_monitor
from timefence.platform.base import UnsupportedActivityMonitor
from timefence.platform.detect import current_os
from tests.helpers import make_resource


def test_current_os_aliases():
    assert current_os("macos") == "darwin"
    assert current_os("windows") == "win32"
    assert current_os("win") == "win32"
    assert current_os("linux") == "linux"


def test_create_activity_monitor_windows_is_placeholder():
    monitor = create_activity_monitor("win32")
    assert isinstance(monitor, UnsupportedActivityMonitor)
    snap = monitor.capture()
    assert snap.frontmost is None
    assert snap.idle_seconds == 0
    assert snap.screen_locked is False


def test_create_activity_monitor_linux_is_placeholder():
    monitor = create_activity_monitor("linux")
    assert isinstance(monitor, UnsupportedActivityMonitor)
    assert monitor.capture().frontmost is None


def test_app_ids_uses_os_specific_map():
    resource = make_resource(
        type="app",
        app_ids={
            "darwin": ["com.google.Chrome"],
            "win32": ["chrome.exe"],
            "linux": ["google-chrome"],
        },
    )
    assert app_ids_for(resource, os_name="darwin") == ["com.google.Chrome"]
    assert app_ids_for(resource, os_name="windows") == ["chrome.exe"]
    assert app_ids_for(resource, os_name="linux") == ["google-chrome"]


def test_app_ids_falls_back_to_bundle_ids_on_macos():
    resource = make_resource(type="app", bundle_ids=["com.apple.Safari"])
    assert app_ids_for(resource, os_name="darwin") == ["com.apple.Safari"]
    assert app_ids_for(resource, os_name="win32") == []


def test_find_resource_by_app_id_on_windows_executables():
    resources = {
        "chrome": make_resource(enabled=True, type="app", executables=["chrome.exe"]),
    }
    match = find_resource_by_app_id(resources, "Chrome.EXE", os_name="win32")
    assert match is not None
    assert match[0] == "chrome"


def test_uses_app_capture_for_app_ids():
    assert uses_app_capture(make_resource(app_ids={"win32": ["roblox.exe"]})) is True
    assert uses_app_capture(make_resource(type="website", url_contains=["youtube.com/"])) is False
