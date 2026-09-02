"""Serves the static parent unlock / rules editor page (`parent.html`)."""

from pathlib import Path

PARENT_HTML = Path(__file__).with_name("parent.html")


def render():
    return PARENT_HTML.read_text(encoding="utf-8")
