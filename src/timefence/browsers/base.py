"""Browser tab inspect/close. OS-specific adapters live under `browsers/<os>/`.

A website resource lists `browser` or `browsers` in rules.json. The registry
picks adapters for the current OS. Add Safari/Edge/Firefox by implementing
`BrowserAdapter` and registering it — `resources/youtube.py` does not change.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TabSnapshot:
    """Front tab of a browser that is currently frontmost."""

    url: str
    title: str = ""
    playback: str = ""
    browser: str = ""
    raw: str = ""


class BrowserAdapter(ABC):
    """One browser on one OS. Inspect only when that browser is the frontmost app."""

    name = ""

    @abstractmethod
    def read_front_tab(self, resource=None, run=None) -> Optional[TabSnapshot]:
        """Active tab if this browser is frontmost and the URL matches `resource`.

        `run` is subprocess.run (tests patch the caller's subprocess).
        Return None when this browser is in the background or the tab is not a match.
        """

    @abstractmethod
    def close_matching_tabs(self, resource=None, run=None) -> None:
        """Close tabs whose URLs match `resource`. Leave other tabs and the browser running."""
