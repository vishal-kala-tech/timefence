import subprocess

ACTIVE_SCRIPT = """
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

            if currentURL contains "youtube.com/" or currentURL contains "youtu.be/" then
                return "YES"
            end if
        end if
    end tell
end if

return "NO"
"""

CLOSE_SCRIPT = """
tell application "Google Chrome"
    repeat with currentWindow in windows
        set tabsToClose to {}

        repeat with currentTab in tabs of currentWindow
            set currentURL to URL of currentTab

            if currentURL contains "youtube.com/" or currentURL contains "youtu.be/" then
                set end of tabsToClose to currentTab
            end if
        end repeat

        repeat with currentTab in tabsToClose
            close currentTab
        end repeat
    end repeat
end tell
"""


def is_active(resource):
    result = subprocess.run(
        ["osascript", "-e", ACTIVE_SCRIPT],
        capture_output=True,
        text=True,
    )

    return result.stdout.strip() == "YES"


def enforce(resource):
    subprocess.run(
        ["osascript", "-e", CLOSE_SCRIPT],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
