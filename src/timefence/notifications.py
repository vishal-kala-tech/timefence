import json
import logging
import subprocess

BLOCK_COUNTDOWN_SECONDS = 6


def _ping():
    try:
        subprocess.Popen(
            ["afplay", "/System/Library/Sounds/Ping.aiff"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def overlay_script(title: str, message: str, seconds: int = BLOCK_COUNTDOWN_SECONDS) -> str:
    """One floating window whose label counts down. No buttons; it cannot be cancelled."""
    seconds = max(1, int(seconds))
    return f'''
ObjC.import("Cocoa");

const title = {json.dumps(title)};
const body = {json.dumps(message)};
const seconds = {seconds};

const app = $.NSApplication.sharedApplication;
app.setActivationPolicy($.NSApplicationActivationPolicyAccessory);

const win = $.NSWindow.alloc.initWithContentRectStyleMaskBackingDefer(
    $.NSMakeRect(0, 0, 420, 170),
    $.NSWindowStyleMaskTitled,
    $.NSBackingStoreBuffered,
    false
);
win.title = title;
win.level = $.NSStatusWindowLevel;
win.releasedWhenClosed = true;
try {{
    win.standardWindowButton($.NSWindowCloseButton).hidden = true;
    win.standardWindowButton($.NSWindowMiniaturizeButton).hidden = true;
    win.standardWindowButton($.NSWindowZoomButton).hidden = true;
}} catch (e) {{}}

const label = $.NSTextField.alloc.initWithFrame($.NSMakeRect(20, 16, 380, 120));
label.bezeled = false;
label.drawsBackground = false;
label.editable = false;
label.selectable = false;
label.alignment = $.NSTextAlignmentCenter;
label.font = $.NSFont.systemFontOfSize(16);
try {{
    label.cell.wraps = true;
}} catch (e) {{}}
win.contentView.addSubview(label);
win.center;
win.makeKeyAndOrderFront(app);
app.activateIgnoringOtherApps(true);

for (let remaining = seconds; remaining >= 1; remaining--) {{
    label.stringValue = body + "\\n\\n" + remaining;
    win.displayIfNeeded;
    $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(1));
}}

win.orderOut(app);
win.close;
'''


block_countdown_script = overlay_script


def _run_overlay(title: str, message: str, seconds: int, *, wait: bool) -> bool:
    seconds = max(1, int(seconds))
    script = overlay_script(title, message, seconds)
    _ping()
    try:
        if wait:
            result = subprocess.run(
                ["osascript", "-l", "JavaScript"],
                input=script,
                text=True,
                capture_output=True,
                timeout=seconds + 8,
                check=False,
            )
            if result.returncode != 0:
                err = (result.stderr or result.stdout or "").strip()
                logging.error(
                    "Overlay failed: %s", err or f"osascript exit {result.returncode}"
                )
                return False
            return True

        proc = subprocess.Popen(
            ["osascript", "-l", "JavaScript"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            text=True,
        )
        proc.stdin.write(script)
        proc.stdin.close()
    except Exception:
        logging.exception("Overlay failed")
        return False
    return True


def show_notification(title: str, message: str, seconds: int = BLOCK_COUNTDOWN_SECONDS) -> bool:
    """Show the same 6-second countdown window as a block, without pausing the controller.

    Launched in the background so usage tracking and enforcement continue
    while the alert is on screen.
    """
    return _run_overlay(title, message, seconds, wait=False)


def show_block_countdown(title: str, message: str, seconds: int = BLOCK_COUNTDOWN_SECONDS) -> bool:
    """Show a 6-second countdown in one window, then return so the caller can enforce.

    Blocks the current thread until the countdown finishes. Failures are
    logged; the caller should still enforce.
    """
    return _run_overlay(title, message, seconds, wait=True)
