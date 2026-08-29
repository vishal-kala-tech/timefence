import json
import logging
import re
import subprocess
from urllib.error import URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen

DEFAULT_URL_CONTAINS = ("youtube.com/", "youtu.be/")
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,20}$")
TITLE_SUFFIX = " - YouTube"
OEMBED_URL = "https://www.youtube.com/oembed?format=json&url="
_metadata_cache = {}


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


def clean_title(title):
    text = (title or "").strip()
    if text in ("missing value", "YouTube"):
        return ""
    if text.endswith(TITLE_SUFFIX):
        text = text[: -len(TITLE_SUFFIX)].strip()
    return text


def clean_channel(name):
    text = " ".join((name or "").split())
    if text.lower() in ("missing value", "undefined", "null"):
        return ""
    return text


def parse_video(url, title="", channel=""):
    if not url:
        return None
    parsed = urlparse(url.strip())
    host = (parsed.netloc or "").lower()
    path = parsed.path or ""
    video_id = None
    kind = "watch"

    if "youtu.be" in host:
        video_id = path.strip("/").split("/")[0]
    else:
        parts = [part for part in path.split("/") if part]
        lowered = [part.lower() for part in parts]
        if "shorts" in lowered:
            idx = lowered.index("shorts")
            if idx + 1 < len(parts):
                video_id = parts[idx + 1]
                kind = "shorts"
        elif "embed" in lowered:
            idx = lowered.index("embed")
            if idx + 1 < len(parts):
                video_id = parts[idx + 1]
        elif "watch" in lowered:
            video_id = (parse_qs(parsed.query).get("v") or [None])[0]
        else:
            video_id = (parse_qs(parsed.query).get("v") or [None])[0]

    if not video_id:
        return None
    video_id = video_id.split("?")[0].split("&")[0].strip()
    if not VIDEO_ID_RE.fullmatch(video_id):
        return None

    if kind == "shorts":
        canonical = f"https://www.youtube.com/shorts/{video_id}"
    else:
        canonical = f"https://www.youtube.com/watch?v={video_id}"

    return {
        "id": video_id,
        "title": clean_title(title),
        "channel": clean_channel(channel),
        "url": canonical,
    }


def _get_json(url):
    request = Request(url, headers={"User-Agent": "TimeFence/1.0"})
    with urlopen(request, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_oembed(url):
    if not url:
        return None
    try:
        data = _get_json(OEMBED_URL + quote(url, safe=""))
    except (OSError, URLError, TimeoutError, ValueError) as exc:
        logging.debug("YouTube oEmbed failed for %s: %s", url, exc)
        return None
    if not isinstance(data, dict):
        return None
    return {
        "title": clean_title(data.get("title") or ""),
        "channel": clean_channel(data.get("author_name") or ""),
    }


def lookup_metadata(video_id):
    if not video_id:
        return None
    if video_id in _metadata_cache:
        return _metadata_cache[video_id]
    result = fetch_oembed(f"https://www.youtube.com/watch?v={video_id}")
    _metadata_cache[video_id] = result
    return result


def _apply_metadata(video, resource=None):
    if not video:
        return video
    extra = lookup_metadata(video.get("id"))
    if not extra:
        return video
    if extra.get("channel"):
        video["channel"] = extra["channel"]
    if extra.get("title") and not video.get("title"):
        video["title"] = extra["title"]
    return video


def inspect_script(resource):
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
            if urlMatched then
                set currentTitle to title of active tab of front window
                return currentURL & linefeed & currentTitle
            end if
        end if
    end tell
end if

return ""
'''


def active_script(resource):
    return inspect_script(resource)


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


ACTIVE_SCRIPT = inspect_script({})
CLOSE_SCRIPT = close_script({})


def inspect(resource):
    result = subprocess.run(
        ["osascript", "-e", inspect_script(resource or {})],
        capture_output=True,
        text=True,
    )
    raw = (result.stdout or "").strip()
    if not raw:
        return None
    lines = raw.splitlines()
    url = lines[0].strip() if lines else ""
    if url in ("", "missing value", "NO", "YES") or not url_matches(url, resource):
        return None
    title = clean_title(lines[1] if len(lines) > 1 else "")
    video = _apply_metadata(parse_video(url, title), resource)
    return {
        "url": url,
        "title": (video or {}).get("title") or title,
        "channel": (video or {}).get("channel") or "",
        "video": video,
    }


def is_active(resource):
    return inspect(resource) is not None


def enforce(resource):
    subprocess.run(
        ["osascript", "-e", close_script(resource or {})],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
