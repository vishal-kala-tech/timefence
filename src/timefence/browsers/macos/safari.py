"""Safari on macOS via AppleScript. Front window's current tab only.

Playback JS needs Develop → Allow JavaScript from Apple Events, same idea as
Chrome. If JS is denied, playback is treated as playing (fail-open, like Chrome).
"""

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
    match = _match_script(resource)
    js = applescript_string(PLAYBACK_JS)
    return f'''
tell application "System Events"
    set safariFrontmost to false
    if exists process "Safari" then
        set safariFrontmost to frontmost of process "Safari"
    end if
end tell

if safariFrontmost then
    tell application "Safari"
        if (count of windows) > 0 then
            set currentURL to URL of current tab of front window
            {match}
            if urlMatched then
                set currentTitle to name of current tab of front window
                set playback to "unknown"
                try
                    set playback to do JavaScript {js} in current tab of front window
                end try
                return currentURL & linefeed & currentTitle & linefeed & playback
            end if
        end if
    end tell
end if

return ""
'''


def browse_script():
    return '''
tell application "System Events"
    set safariFrontmost to false
    if exists process "Safari" then
        set safariFrontmost to frontmost of process "Safari"
    end if
end tell

if safariFrontmost then
    tell application "Safari"
        if (count of windows) > 0 then
            set currentURL to URL of current tab of front window
            set currentTitle to name of current tab of front window
            return currentURL & linefeed & currentTitle
        end if
    end tell
end if

return ""
'''


def close_script(resource=None):
    match = _match_script(resource)
    return f'''
tell application "Safari"
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


class MacOSSafariAdapter(BrowserAdapter):
    name = "safari"

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
