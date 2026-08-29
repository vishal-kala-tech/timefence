import subprocess

DEFAULT_URL_CONTAINS = ("youtube.com/", "youtu.be/")


def _patterns(resource, key, default):
    values = (resource or {}).get(key)
    if values is None:
        return list(default)
    return [str(item) for item in values]


def url_matches(url, resource):
    if not url:
        return False
    contains = _patterns(resource, "url_contains", DEFAULT_URL_CONTAINS)
    excludes = _patterns(resource, "url_excludes", ())
    if not any(token in url for token in contains):
        return False
    return not any(token in url for token in excludes)


def _applescript_string(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _or_contains(variable, patterns):
    if not patterns:
        return "false"
    return " or ".join(f"{variable} contains {_applescript_string(token)}" for token in patterns)


def _url_match_script(resource, variable="currentURL"):
    contains = _patterns(resource, "url_contains", DEFAULT_URL_CONTAINS)
    excludes = _patterns(resource, "url_excludes", ())
    script = f"set urlMatched to {_or_contains(variable, contains)}\n"
    if excludes:
        script += f"if {_or_contains(variable, excludes)} then set urlMatched to false\n"
    return script


def active_script(resource):
    match = _url_match_script(resource)
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
            if urlMatched then return "YES"
        end if
    end tell
end if

return "NO"
'''


def close_script(resource):
    match = _url_match_script(resource)
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


ACTIVE_SCRIPT = active_script({})
CLOSE_SCRIPT = close_script({})


def is_active(resource):
    result = subprocess.run(
        ["osascript", "-e", active_script(resource or {})],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() == "YES"


def enforce(resource):
    subprocess.run(
        ["osascript", "-e", close_script(resource or {})],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
