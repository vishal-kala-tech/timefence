from unittest.mock import MagicMock

from timefence.browsers import adapters_for, requested_browsers
from timefence.browsers.macos import chrome as macos_chrome
from timefence.browsers.macos import safari as macos_safari
from tests.helpers import make_resource


def test_requested_browsers_prefers_resource_list():
    resource = make_resource(browsers=["safari", "chrome"])
    assert requested_browsers(resource) == ["safari", "chrome"]


def test_requested_browsers_singular_browser():
    resource = make_resource(browser="safari")
    assert requested_browsers(resource) == ["safari"]


def test_requested_browsers_falls_back_to_config_then_chrome():
    assert requested_browsers({}, cfg={"browsers": ["safari"]}) == ["safari"]
    assert requested_browsers({}, cfg={}, os_name="darwin") == ["chrome"]


def test_adapters_for_macos_chrome_and_safari():
    resource = make_resource(browsers=["chrome", "safari"])
    names = [adapter.name for adapter in adapters_for(resource, os_name="darwin")]
    assert names == ["chrome", "safari"]


def test_safari_scripts_target_safari_not_chrome():
    script = macos_safari.inspect_script({"url_contains": ["youtube.com/"]})
    assert "tell application \"Safari\"" in script
    assert "do JavaScript" in script
    assert "Google Chrome" not in script
    close = macos_safari.close_script({"url_contains": ["youtube.com/"]})
    assert "tell application \"Safari\"" in close
    assert "youtube.com/" in close


def test_chrome_adapter_reads_front_tab(monkeypatch):
    run = MagicMock(return_value=MagicMock(stdout="https://www.youtube.com/watch?v=dQw4w9WgXcQ\nSong\nplaying\n"))
    tab = macos_chrome.MacOSChromeAdapter().read_front_tab({"url_contains": ["youtube.com/"]}, run=run)
    assert tab.url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert tab.browser == "chrome"
    run.assert_called_once()
    assert "Google Chrome" in run.call_args.args[0][2]


def test_youtube_inspect_uses_safari_when_configured(monkeypatch):
    from timefence.resources import youtube

    def run(cmd, **_kwargs):
        script = cmd[2]
        if "Safari" in script:
            return MagicMock(stdout="https://www.youtube.com/watch?v=dQw4w9WgXcQ\nSong - YouTube\nplaying\n")
        return MagicMock(stdout="")

    monkeypatch.setattr(youtube.subprocess, "run", run)
    page = youtube.inspect({"browsers": ["chrome", "safari"], "url_contains": ["youtube.com/"]})
    assert page["url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert page["browser"] == "safari"
    assert page["video"]["id"] == "dQw4w9WgXcQ"
