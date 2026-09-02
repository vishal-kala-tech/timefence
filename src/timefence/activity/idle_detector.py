"""Compatibility shim. Implementation lives in `timefence.platform.macos.idle`."""

from ..platform.macos.idle import idle_seconds, is_idle, is_screen_locked

__all__ = ["idle_seconds", "is_idle", "is_screen_locked"]
