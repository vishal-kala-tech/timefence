"""Linux browser placeholders. Use xdotool/AT-SPI or a companion extension."""

import logging

from ..base import BrowserAdapter


class LinuxBrowserAdapter(BrowserAdapter):
    def __init__(self, name):
        self.name = name

    def read_front_tab(self, resource=None, run=None):
        logging.debug("No Linux %s tab adapter yet", self.name)
        return None

    def close_matching_tabs(self, resource=None, run=None):
        logging.debug("No Linux %s tab closer yet", self.name)
