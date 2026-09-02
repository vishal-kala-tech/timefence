"""Resolve BrowserAdapter instances for the current OS and a resource/config."""

import logging

from ..platform.detect import DARWIN, LINUX, WINDOWS, current_os
from .matching import KNOWN_BROWSERS, requested_browsers


class UnimplementedBrowserAdapter:
    """Registered name on this OS but no native tab API yet. Inspect returns None."""

    def __init__(self, name, os_name):
        self.name = name
        self.os_name = os_name

    def read_front_tab(self, resource=None, run=None):
        logging.debug("Browser %s is not implemented on %s", self.name, self.os_name)
        return None

    def read_any_front_tab(self, run=None):
        return self.read_front_tab(run=run)

    def close_matching_tabs(self, resource=None, run=None):
        logging.debug("Browser %s tab close is not implemented on %s", self.name, self.os_name)


def _macos_adapter(name):
    from .macos import MACOS_ADAPTERS

    cls = MACOS_ADAPTERS.get(name)
    return cls() if cls is not None else None


def _windows_adapter(name):
    from .windows import WindowsBrowserAdapter

    return WindowsBrowserAdapter(name)


def _linux_adapter(name):
    from .linux import LinuxBrowserAdapter

    return LinuxBrowserAdapter(name)


def adapter_for(name, os_name=None):
    """One adapter, or UnimplementedBrowserAdapter if the OS has no code yet."""
    os_name = current_os(os_name)
    key = str(name or "").strip().lower()
    if not key:
        return None
    if os_name == DARWIN:
        found = _macos_adapter(key)
        if found is not None:
            return found
    elif os_name == WINDOWS:
        return _windows_adapter(key)
    elif os_name == LINUX:
        return _linux_adapter(key)
    return UnimplementedBrowserAdapter(key, os_name)


def adapters_for(resource=None, cfg=None, os_name=None):
    """Adapters in config order. Unknown names are skipped with a warning."""
    os_name = current_os(os_name)
    out = []
    for name in requested_browsers(resource, cfg=cfg, os_name=os_name):
        if name not in KNOWN_BROWSERS:
            logging.warning("Unknown browser %r; ignored", name)
            continue
        adapter = adapter_for(name, os_name=os_name)
        if adapter is not None:
            out.append(adapter)
    return out


def read_matching_tab(resource=None, cfg=None, run=None):
    """First matching front tab across configured browsers (frontmost browser wins)."""
    for adapter in adapters_for(resource, cfg=cfg):
        try:
            tab = adapter.read_front_tab(resource, run=run)
        except Exception:
            logging.debug("Browser %s inspect failed", getattr(adapter, "name", "?"), exc_info=True)
            continue
        if tab is not None:
            return tab
    return None


def read_frontmost_tab(cfg=None, run=None):
    """Front tab of whichever configured browser is in front, with no URL filter."""
    for adapter in adapters_for(resource=None, cfg=cfg):
        reader = getattr(adapter, "read_any_front_tab", None)
        try:
            tab = reader(run=run) if callable(reader) else adapter.read_front_tab(resource=None, run=run)
        except Exception:
            logging.debug("Browser %s browse inspect failed", getattr(adapter, "name", "?"), exc_info=True)
            continue
        if tab is not None:
            return tab
    return None


def close_matching_tabs(resource=None, cfg=None, run=None):
    """Close matching tabs in every configured browser (not only the frontmost)."""
    for adapter in adapters_for(resource, cfg=cfg):
        try:
            adapter.close_matching_tabs(resource, run=run)
        except Exception:
            logging.debug("Browser %s close failed", getattr(adapter, "name", "?"), exc_info=True)
