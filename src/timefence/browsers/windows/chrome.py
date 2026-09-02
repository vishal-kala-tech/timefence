"""Windows browser placeholders. Use UI Automation or a companion extension."""

import logging

from ..base import BrowserAdapter


class WindowsBrowserAdapter(BrowserAdapter):
    """Inspect/close is not implemented. A native adapter or extension should replace this."""

    def __init__(self, name):
        self.name = name

    def read_front_tab(self, resource=None, run=None):
        logging.debug("No Windows %s tab adapter yet", self.name)
        return None

    def close_matching_tabs(self, resource=None, run=None):
        logging.debug("No Windows %s tab closer yet", self.name)
