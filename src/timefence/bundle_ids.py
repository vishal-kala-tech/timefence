"""Turn macOS bundle IDs into short labels. Parent-edited names live in SQLite."""

import re

FRIENDLY_IDS = {
    "com.apple.terminal": "Terminal",
    "com.apple.finder": "Finder",
    "com.apple.safari": "Safari",
    "com.apple.iterm2": "iTerm",
    "com.googlecode.iterm2": "iTerm",
    "com.google.chrome": "Chrome",
    "com.microsoft.vscode": "VS Code",
    "com.microsoft.vscodeinsiders": "VS Code Insiders",
    "com.microsoft.visual-studio": "Visual Studio",
    "com.todesktop.230313mzl4w4u92": "Cursor",
    "visual_studio": "VS Code",
}

_LAST_SEGMENT_LABELS = {
    "vscode": "VS Code",
    "vscodeinsiders": "VS Code Insiders",
    "iterm2": "iTerm",
    "terminal": "Terminal",
    "finder": "Finder",
}


def is_bundle_id(value):
    raw = str(value or "").strip()
    if not raw or "://" in raw or " " in raw:
        return False
    return "." in raw


def humanize_bundle_id(value):
    raw = str(value or "").strip()
    if not raw:
        return "App"
    mapped = FRIENDLY_IDS.get(raw.lower())
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
