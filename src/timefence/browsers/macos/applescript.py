"""AppleScript helpers for macOS browser adapters."""

import subprocess

PLAYBACK_JS = (
    "(function(){"
    "var p=document.querySelector('.html5-video-player');"
    "if(p){"
    "if(p.classList.contains('paused-mode')||p.classList.contains('unstarted-mode'))return 'paused';"
    "if(p.classList.contains('playing-mode'))return 'playing';"
    "}"
    "var v=document.querySelector('video.html5-main-video')||document.querySelector('video');"
    "if(!v)return 'unknown';"
    "return v.paused?'paused':'playing';"
    "})()"
)


def applescript_string(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def or_contains(variable, patterns):
    if not patterns:
        return "false"
    return " or ".join(f"{variable} contains {applescript_string(token)}" for token in patterns)


def url_match_script(contains, excludes, variable="currentURL"):
    script = f"set urlMatched to {or_contains(variable, contains)}\n"
    if excludes:
        script += f"if {or_contains(variable, excludes)} then set urlMatched to false\n"
    return script


def run_osascript(script, *, capture=True, run=None):
    """Call osascript with the same kwargs the old youtube/browse helpers used (tests assert them)."""
    runner = run or subprocess.run
    if capture:
        return runner(["osascript", "-e", script], capture_output=True, text=True)
    return runner(
        ["osascript", "-e", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def parse_tab_output(raw):
    text = (raw or "").strip()
    if not text:
        return None
    lines = text.splitlines()
    url = lines[0].strip() if lines else ""
    if url in ("", "missing value", "NO", "YES"):
        return None
    title = lines[1].strip() if len(lines) > 1 else ""
    playback = lines[2].strip() if len(lines) > 2 else ""
    return url, title, playback
