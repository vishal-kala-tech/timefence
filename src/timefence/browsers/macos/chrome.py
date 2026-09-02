"""Google Chrome on macOS via AppleScript. Front window's active tab only."""

from ..matching import DEFAULT_URL_CONTAINS, pattern_list
from ..base import BrowserAdapter, TabSnapshot
from .applescript import (
    PLAYBACK_JS,
    applescript_string,
    parse_tab_output,
    run_osascript,
    url_match_script,
)


def _match_script(resource):
    contains = pattern_list(resource, "url_contains", DEFAULT_URL_CONTAINS)
    excludes = pattern_list(resource, "url_excludes", ())
    return url_match_script(contains, excludes)


def inspect_script(resource=None):
    """AppleScript: only when Chrome is frontmost, return URL/title/playback of the active tab."""
    match = _match_script(resource)
    js = applescript_string(PLAYBACK_JS)
    return f'''
tell application "System Events"
    set chromeFrontmost to false
    if exists process "Google Chrome" then
        set chromeFrontmost to frontmost of process "Google Chrome"
    end if
end tell

if chromeFrontmost then
    tell application "Google Chrome"
        if (count of windows) > 0 then
            set currentURL to URL of active tab of front window
            {match}
            if urlMatched then
                set currentTitle to title of active tab of front window
                set playback to "unknown"
                try
                    set playback to execute front window's active tab javascript {js}
                end try
                return currentURL & linefeed & currentTitle & linefeed & playback
            end if
        end if
    end tell
end if

return ""
'''


def browse_script():
    """Any front-tab URL (no youtube filter). Used by the browse log."""
    return '''
tell application "System Events"
    set chromeFrontmost to false
    if exists process "Google Chrome" then
        set chromeFrontmost to frontmost of process "Google Chrome"
    end if
end tell

if chromeFrontmost then
    tell application "Google Chrome"
        if (count of windows) > 0 then
            set currentURL to URL of active tab of front window
            set currentTitle to title of active tab of front window
            return currentURL & linefeed & currentTitle
        end if
    end tell
end if

return ""
'''


def close_script(resource=None):
    """Close every Chrome tab whose URL matches; leave other tabs and Chrome running."""
    match = _match_script(resource)
    return f'''
tell application "Google Chrome"
    repeat with currentWindow in windows
        set tabsToClose to {{}}
        repeat with currentTab in tabs of currentWindow
            set currentURL to URL of currentTab
            {match}
            if urlMatched then set end of tabsToClose to currentTab
        end repeat
        repeat with currentTab in tabsToClose
            close currentTab
        end repeat
    end repeat
end tell
'''


class MacOSChromeAdapter(BrowserAdapter):
    name = "chrome"

    def read_front_tab(self, resource=None, run=None):
        result = run_osascript(inspect_script(resource), capture=True, run=run)
        parsed = parse_tab_output(result.stdout if result is not None else "")
        if parsed is None:
            return None
        url, title, playback = parsed
        return TabSnapshot(url=url, title=title, playback=playback, browser=self.name, raw=(result.stdout or ""))

    def read_any_front_tab(self, run=None):
        result = run_osascript(browse_script(), capture=True, run=run)
        parsed = parse_tab_output(result.stdout if result is not None else "")
        if parsed is None:
            return None
        url, title, playback = parsed
        return TabSnapshot(url=url, title=title, playback=playback, browser=self.name)

    def close_matching_tabs(self, resource=None, run=None):
        run_osascript(close_script(resource), capture=False, run=run)
