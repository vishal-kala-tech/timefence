"""Normalize sys.platform to the keys used in `app_ids` and the adapter registry."""

import sys

# Canonical names stored in rules.json `app_ids` / used by factory lookup.
DARWIN = "darwin"
WINDOWS = "win32"
LINUX = "linux"

_ALIASES = {
    "darwin": DARWIN,
    "macos": DARWIN,
    "mac": DARWIN,
    "win32": WINDOWS,
    "windows": WINDOWS,
    "win": WINDOWS,
    "cygwin": WINDOWS,
    "linux": LINUX,
}


def current_os(platform_name=None):
    """`darwin`, `win32`, or `linux`. Unknown values are returned as-is (lowercased)."""
    raw = (platform_name if platform_name is not None else sys.platform) or ""
    key = str(raw).strip().lower()
    return _ALIASES.get(key, key)


def os_aliases(os_name=None):
    """All config keys that mean the same OS as `os_name` (or the current OS)."""
    canonical = current_os(os_name)
    return tuple(name for name, value in _ALIASES.items() if value == canonical)
