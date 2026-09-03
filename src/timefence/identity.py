"""Canonical resource identity: (resource_type, resource_id).

Three layers of activity, counted separately and never added together for
screen time:

- app: physical foreground process (bundle ID). This is screen time.
- website: which site that foreground browser time was spent on.
- video_category: further classification of a site (YouTube videos vs Shorts).

Chrome for 20 minutes on a YouTube video therefore stores 20 minutes on the
Chrome app, 20 minutes on youtube.com, and 20 minutes on youtube_videos.
Total screen time is the app layer only (20 minutes), not 60.
"""

import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

RESOURCE_TYPE_APP = "app"
RESOURCE_TYPE_WEBSITE = "website"
RESOURCE_TYPE_VIDEO_CATEGORY = "video_category"

YOUTUBE_VIDEOS_RESOURCE_ID = "youtube_videos"
YOUTUBE_SHORTS_RESOURCE_ID = "youtube_shorts"
YOUTUBE_WEBSITE_RESOURCE_ID = "youtube.com"
YOUTUBE_PLATFORM = "youtube"

IDENTIFIER_BUNDLE_ID = "bundle_id"
IDENTIFIER_DOMAIN = "domain"
IDENTIFIER_INTERNAL = "internal"
IDENTIFIER_EXECUTABLE_PATH = "executable_path"
IDENTIFIER_PROCESS_NAME = "process_name"

BROWSER_BUNDLE_IDS = {
    "chrome": "com.google.Chrome",
    "safari": "com.apple.Safari",
    "firefox": "org.mozilla.firefox",
    "edge": "com.microsoft.edgemac",
}

BROWSER_DISPLAY_NAMES = {
    "com.google.chrome": "Google Chrome",
    "com.apple.safari": "Safari",
    "org.mozilla.firefox": "Firefox",
    "com.microsoft.edgemac": "Edge",
}

_DEFAULT_DISPLAY_NAMES = {
    (RESOURCE_TYPE_APP, "com.apple.terminal"): "Terminal",
    (RESOURCE_TYPE_APP, "com.apple.finder"): "Finder",
    (RESOURCE_TYPE_APP, "com.apple.safari"): "Safari",
    (RESOURCE_TYPE_APP, "com.apple.iterm2"): "iTerm",
    (RESOURCE_TYPE_APP, "com.googlecode.iterm2"): "iTerm",
    (RESOURCE_TYPE_APP, "com.google.chrome"): "Google Chrome",
    (RESOURCE_TYPE_APP, "com.microsoft.vscode"): "VS Code",
    (RESOURCE_TYPE_APP, "com.microsoft.vscodeinsiders"): "VS Code Insiders",
    (RESOURCE_TYPE_APP, "com.microsoft.visual-studio"): "Visual Studio",
    (RESOURCE_TYPE_APP, "com.todesktop.230313mzl4w4u92"): "Cursor",
    (RESOURCE_TYPE_APP, "com.roblox.roblox"): "Roblox",
    (RESOURCE_TYPE_APP, "com.roblox.robloxplayer"): "Roblox",
    (RESOURCE_TYPE_APP, "com.jetbrains.pycharm"): "PyCharm",
    (RESOURCE_TYPE_WEBSITE, "youtube.com"): "YouTube",
    (RESOURCE_TYPE_WEBSITE, "github.com"): "GitHub",
    (RESOURCE_TYPE_WEBSITE, "chatgpt.com"): "ChatGPT",
    (RESOURCE_TYPE_VIDEO_CATEGORY, YOUTUBE_VIDEOS_RESOURCE_ID): "YouTube Videos",
    (RESOURCE_TYPE_VIDEO_CATEGORY, YOUTUBE_SHORTS_RESOURCE_ID): "YouTube Shorts",
}

_LAST_SEGMENT_LABELS = {
    "vscode": "VS Code",
    "vscodeinsiders": "VS Code Insiders",
    "iterm2": "iTerm",
    "terminal": "Terminal",
    "finder": "Finder",
}

_YOUTUBE_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com", "m.youtube.com")


def listed_resources(cfg_or_resources):
    """Return the resources list from a config dict, or the list itself."""
    if isinstance(cfg_or_resources, list):
        items = cfg_or_resources
    elif isinstance(cfg_or_resources, dict):
        items = cfg_or_resources.get("resources")
        if not isinstance(items, list):
            items = []
    else:
        items = []
    return [item for item in items if isinstance(item, dict)]


def resource_type_of(resource, default=RESOURCE_TYPE_APP):
    text = str((resource or {}).get("resource_type") or default).strip()
    return text or default


def resource_id_of(resource):
    return str((resource or {}).get("resource_id") or "").strip()


def resource_key(resource):
    return (resource_type_of(resource), resource_id_of(resource))


def match_ids_for(resource):
    resource = resource or {}
    ids = [resource_id_of(resource)]
    extra = resource.get("match_ids")
    if extra is None:
        extra = resource.get("bundle_ids")
    if isinstance(extra, str):
        extra = [extra]
    if isinstance(extra, list):
        ids.extend(str(item).strip() for item in extra)
    seen = set()
    out = []
    for item in ids:
        key = item.lower()
        if not item or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def find_listed_resource(cfg_or_resources, resource_type, resource_id):
    needle_type = str(resource_type or "").strip()
    needle_id = str(resource_id or "").strip().lower()
    if not needle_type or not needle_id:
        return None
    for resource in listed_resources(cfg_or_resources):
        if resource_type_of(resource) != needle_type:
            continue
        if needle_type == RESOURCE_TYPE_APP:
            ids = [item.lower() for item in match_ids_for(resource)]
            if needle_id in ids:
                return resource
        elif resource_id_of(resource).lower() == needle_id:
            return resource
    return None


def identifier_type_for(resource_type):
    if resource_type == RESOURCE_TYPE_APP:
        return IDENTIFIER_BUNDLE_ID
    if resource_type == RESOURCE_TYPE_WEBSITE:
        return IDENTIFIER_DOMAIN
    if resource_type == RESOURCE_TYPE_VIDEO_CATEGORY:
        return IDENTIFIER_INTERNAL
    return ""


def is_bundle_id(value):
    raw = str(value or "").strip()
    if not raw or "://" in raw or " " in raw:
        return False
    return "." in raw


def humanize_bundle_id(value):
    raw = str(value or "").strip()
    if not raw:
        return "App"
    mapped = _DEFAULT_DISPLAY_NAMES.get((RESOURCE_TYPE_APP, raw.lower()))
    if mapped:
        return mapped
    if "." in raw and " " not in raw:
        last = raw.rsplit(".", 1)[-1]
        mapped = _LAST_SEGMENT_LABELS.get(last.lower())
        if mapped:
            return mapped
        pieces = re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|\d+", last)
        if pieces:
            return " ".join(pieces)
        return last
    return raw.replace("_", " ").replace("-", " ").title()


def default_display_name(resource_type, resource_id, observed_name=""):
    observed = str(observed_name or "").strip()
    if observed and observed.lower() != str(resource_id or "").strip().lower():
        return observed
    key = (str(resource_type or "").strip(), str(resource_id or "").strip().lower())
    mapped = _DEFAULT_DISPLAY_NAMES.get(key)
    if mapped:
        return mapped
    if resource_type == RESOURCE_TYPE_APP:
        return humanize_bundle_id(resource_id)
    if resource_type == RESOURCE_TYPE_WEBSITE:
        host = str(resource_id or "").strip()
        if host.endswith(".com") and host.count(".") == 1:
            return host[: -len(".com")].replace("-", " ").title()
        return host
    return str(resource_id or "").replace("_", " ").title() or "Resource"


def website_id(value):
    """Normalized domain identity: github.com, youtube.com."""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if "://" in text or "/" in text:
        parsed = urlparse(text if "://" in text else f"https://{text}")
        text = (parsed.netloc or parsed.path or "").lower()
    host = text.split("/")[0].split("?")[0].strip().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if ":" in host and not host.startswith("["):
        name, _, port = host.rpartition(":")
        if port in ("80", "443"):
            host = name
    if host in ("youtu.be", "m.youtube.com", "youtube-nocookie.com"):
        return YOUTUBE_WEBSITE_RESOURCE_ID
    return host


def classify_youtube(url):
    """Return youtube_videos, youtube_shorts, or None."""
    text = str(url or "").strip()
    if not text:
        return None
    parsed = urlparse(text if "://" in text else f"https://{text}")
    host = website_id(parsed.netloc or text)
    if host not in _YOUTUBE_HOSTS and host != YOUTUBE_WEBSITE_RESOURCE_ID:
        return None
    path = (parsed.path or "").lower()
    if "/shorts/" in path or path.rstrip("/").endswith("/shorts"):
        return YOUTUBE_SHORTS_RESOURCE_ID
    return YOUTUBE_VIDEOS_RESOURCE_ID


def browser_resource_id(browser_name, bundle_id=""):
    bundle = str(bundle_id or "").strip()
    if is_bundle_id(bundle):
        return bundle
    return BROWSER_BUNDLE_IDS.get(str(browser_name or "").strip().lower(), bundle)


def browser_display_name(browser_resource_id_value, browser_name=""):
    key = str(browser_resource_id_value or "").strip().lower()
    if key in BROWSER_DISPLAY_NAMES:
        return BROWSER_DISPLAY_NAMES[key]
    name = str(browser_name or "").strip()
    if name:
        return name.title()
    return humanize_bundle_id(browser_resource_id_value) if browser_resource_id_value else ""


def app_resource_id(bundle_id="", executable_path="", process_name=""):
    """Fallback order: bundle ID, executable path, process name."""
    bundle = str(bundle_id or "").strip()
    if is_bundle_id(bundle):
        return bundle, IDENTIFIER_BUNDLE_ID
    path = str(executable_path or "").strip()
    if path:
        return path, IDENTIFIER_EXECUTABLE_PATH
    process = str(process_name or "").strip()
    if process:
        return process, IDENTIFIER_PROCESS_NAME
    return "", ""


def _stamp(now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.replace(microsecond=0).isoformat()


def ensure_resource(
    store,
    resource_type,
    resource_id,
    display_name="",
    identifier_type="",
    metadata=None,
    now=None,
):
    """Insert or refresh a resources row. Preserve created_at."""
    resource_type = str(resource_type or "").strip()
    resource_id = str(resource_id or "").strip()
    if not resource_type or not resource_id:
        return None
    display_name = str(display_name or "").strip() or default_display_name(resource_type, resource_id)
    identifier_type = str(identifier_type or "").strip() or identifier_type_for(resource_type)
    if metadata is None:
        metadata_json = None
    else:
        metadata_json = json.dumps(metadata, separators=(",", ":"))
    return store.ensure_resource(
        resource_type,
        resource_id,
        display_name=display_name,
        identifier_type=identifier_type,
        metadata_json=metadata_json,
        updated_at=_stamp(now),
    )
