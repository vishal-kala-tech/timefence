"""Browser tab adapters. Website resources depend on this package, not AppleScript."""

from .base import BrowserAdapter, TabSnapshot
from .matching import KNOWN_BROWSERS, default_browsers, requested_browsers, url_matches
from .registry import adapter_for, adapters_for, close_matching_tabs, read_frontmost_tab, read_matching_tab

__all__ = [
    "KNOWN_BROWSERS",
    "BrowserAdapter",
    "TabSnapshot",
    "adapter_for",
    "adapters_for",
    "close_matching_tabs",
    "default_browsers",
    "read_frontmost_tab",
    "read_matching_tab",
    "requested_browsers",
    "url_matches",
]
