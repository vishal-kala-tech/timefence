from .chrome import MacOSChromeAdapter, browse_script as chrome_browse_script, close_script as chrome_close_script, inspect_script as chrome_inspect_script
from .safari import MacOSSafariAdapter

MACOS_ADAPTERS = {
    "chrome": MacOSChromeAdapter,
    "safari": MacOSSafariAdapter,
}

__all__ = [
    "MACOS_ADAPTERS",
    "MacOSChromeAdapter",
    "MacOSSafariAdapter",
    "chrome_browse_script",
    "chrome_close_script",
    "chrome_inspect_script",
]
