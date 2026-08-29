import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .status_page import DEFAULT_STATUS_PORT, render, write_html

_lock = threading.Lock()
_server = None
_thread = None
_port = None
_app_dir = None


class _Server(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        logging.debug("status page: " + fmt, *args)

    def _send(self, code, body, content_type):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        app_dir = _app_dir
        if app_dir is None:
            self._send(503, "TimeFence is starting.", "text/plain; charset=utf-8")
            return
        path = (self.path or "/").split("?", 1)[0]
        if path in ("/", "/index.html", "/status.html"):
            try:
                page = render(app_dir)
            except Exception:
                logging.exception("Status page render failed")
                self._send(500, "Could not load TimeFence status.", "text/plain; charset=utf-8")
                return
            self._send(200, page, "text/html; charset=utf-8")
            return
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        self._send(404, "Not found.", "text/plain; charset=utf-8")


def url(port=None):
    return f"http://127.0.0.1:{int(port or DEFAULT_STATUS_PORT)}/"


def stop():
    global _server, _thread, _port
    with _lock:
        server = _server
        _server = None
        _thread = None
        _port = None
    if server is not None:
        try:
            server.shutdown()
        except Exception:
            logging.debug("Status page server shutdown failed", exc_info=True)
        try:
            server.server_close()
        except Exception:
            pass


def _serve(server):
    try:
        server.serve_forever(poll_interval=0.5)
    except Exception:
        logging.exception("Status page server stopped")


def ensure(app_dir, port=DEFAULT_STATUS_PORT):
    """Serve the kid status page on 127.0.0.1. Safe to call every controller cycle."""
    global _server, _thread, _port, _app_dir
    app_dir = Path(app_dir)
    port = int(port)
    with _lock:
        _app_dir = app_dir
        if _server is not None and _port == port:
            return _server, _port
        server = _server
    if server is not None:
        stop()
    try:
        httpd = _Server(("127.0.0.1", port), _Handler)
    except OSError as exc:
        logging.error("Status page could not listen on port %s: %s", port, exc)
        return None, None
    thread = threading.Thread(target=_serve, args=(httpd,), name="timefence-status", daemon=True)
    with _lock:
        bound = httpd.server_address[1]
        _server = httpd
        _thread = thread
        _port = bound
        _app_dir = app_dir
    thread.start()
    logging.info("Kid status page: %s", url(bound))
    try:
        write_html(app_dir)
    except Exception:
        logging.exception("Could not write status.html")
    return httpd, bound
