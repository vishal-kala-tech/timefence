import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from . import parent_auth, parent_page
from .config import load_config, save_config
from .grants import clear_grant, grant_from_config, grant_rows
from .parent_editor import apply_editor, editor_from_config
from .status_page import DEFAULT_STATUS_PORT, render, write_html

_lock = threading.Lock()
_server = None
_thread = None
_port = None
_app_dir = None


class _Server(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def _rules_path(app_dir):
    return Path(app_dir) / "config" / "rules.json"


def _load_rules(app_dir):
    return load_config(_rules_path(app_dir))


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        logging.debug("status page: " + fmt, *args)

    def _path(self):
        raw = (self.path or "/").split("?", 1)[0]
        if len(raw) > 1:
            raw = raw.rstrip("/")
        return raw or "/"

    def _send(self, code, body, content_type, set_cookie=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, code, payload, set_cookie=None):
        self._send(code, json.dumps(payload), "application/json; charset=utf-8", set_cookie=set_cookie)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > 1_000_000:
            raise ValueError("Request is too large")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("Request must be JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("Request must be a JSON object")
        return data

    def _unlocked(self):
        token = parent_auth.parse_cookie_header(self.headers.get("Cookie")).get(parent_auth.COOKIE_NAME)
        return parent_auth.valid_token(_app_dir, token)

    def _require_parent(self):
        if self._unlocked():
            return True
        self._send_json(401, {"error": "Unlock with your parent PIN first."})
        return False

    def _session_payload(self):
        return {
            "has_pin": parent_auth.has_pin(_app_dir),
            "unlocked": self._unlocked(),
        }

    def _grant_payload(self, cfg):
        resources = []
        for name, resource in (cfg.get("resources") or {}).items():
            if not isinstance(resource, dict):
                continue
            resources.append(
                {
                    "id": name,
                    "label": resource.get("display_name") or name,
                    "enabled": bool(resource.get("enabled", True)),
                }
            )
        return {"grants": grant_rows(cfg, Path(_app_dir) / "state"), "resources": resources}

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    def _handle(self, method):
        app_dir = _app_dir
        if app_dir is None:
            self._send(503, "TimeFence is starting.", "text/plain; charset=utf-8")
            return
        path = self._path()
        try:
            if method == "GET" and path in ("/", "/index.html", "/status.html"):
                self._send(200, render(app_dir), "text/html; charset=utf-8")
                return
            if method == "GET" and path in ("/setup", "/setup.html"):
                self._send(200, parent_page.render(), "text/html; charset=utf-8")
                return
            if method == "GET" and path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            if method == "GET" and path == "/api/parent/session":
                self._send_json(200, self._session_payload())
                return
            if method == "POST" and path == "/api/pin":
                self._pin()
                return
            if method == "POST" and path == "/api/logout":
                self._send_json(200, {"ok": True, "has_pin": parent_auth.has_pin(app_dir), "unlocked": False}, set_cookie=parent_auth.cookie_header(clear=True))
                return
            if method == "GET" and path == "/api/rules":
                if not self._require_parent():
                    return
                cfg = _load_rules(app_dir)
                self._send_json(200, editor_from_config(cfg))
                return
            if method == "PUT" and path == "/api/rules":
                if not self._require_parent():
                    return
                cfg = save_config(_rules_path(app_dir), apply_editor(_load_rules(app_dir), self._read_json()))
                logging.info("Parent saved rules revision=%s", cfg.get("revision"))
                self._send_json(200, editor_from_config(cfg))
                return
            if method == "GET" and path == "/api/grants":
                if not self._require_parent():
                    return
                self._send_json(200, self._grant_payload(_load_rules(app_dir)))
                return
            if method == "POST" and path == "/api/grants":
                if not self._require_parent():
                    return
                body = self._read_json()
                try:
                    minutes = int(body.get("minutes"))
                except (TypeError, ValueError):
                    raise ValueError("Minutes must be a whole number")
                cfg = _load_rules(app_dir)
                name, _grant = grant_from_config(cfg, Path(app_dir) / "state", body.get("resource"), minutes)
                logging.info("Parent granted %s +%s min", name, body.get("minutes"))
                payload = self._grant_payload(cfg)
                payload["granted"] = {"id": name, "summary": next((row["summary"] for row in payload["grants"] if row["id"] == name), None)}
                self._send_json(200, payload)
                return
            if method == "DELETE" and path.startswith("/api/grants/"):
                if not self._require_parent():
                    return
                name = unquote(path[len("/api/grants/") :]).strip()
                if not name:
                    self._send_json(400, {"error": "Missing resource"})
                    return
                cfg = _load_rules(app_dir)
                resources = cfg.get("resources") or {}
                if name not in resources:
                    self._send_json(404, {"error": f"Unknown resource {name!r}"})
                    return
                clear_grant(Path(app_dir) / "state", name)
                logging.info("Parent cleared grant for %s", name)
                self._send_json(200, self._grant_payload(cfg))
                return
            self._send(404, "Not found.", "text/plain; charset=utf-8")
        except FileNotFoundError:
            self._send_json(503, {"error": "TimeFence rules are not installed yet."})
        except ValueError as exc:
            code = 403 if str(exc) == "Wrong PIN" else 400
            self._send_json(code, {"error": str(exc)})
        except Exception:
            logging.exception("Parent/status request failed")
            if path.startswith("/api/"):
                self._send_json(500, {"error": "Something went wrong."})
            else:
                self._send(500, "Could not load TimeFence.", "text/plain; charset=utf-8")

    def _pin(self):
        pin = str((self._read_json() or {}).get("pin") or "")
        if parent_auth.has_pin(_app_dir):
            token = parent_auth.unlock(_app_dir, pin)
        else:
            token = parent_auth.set_pin(_app_dir, pin)
        self._send_json(
            200,
            {"ok": True, "has_pin": True, "unlocked": True},
            set_cookie=parent_auth.cookie_header(token),
        )


def url(port=None):
    return f"http://127.0.0.1:{int(port or DEFAULT_STATUS_PORT)}/"


def setup_url(port=None):
    return f"http://127.0.0.1:{int(port or DEFAULT_STATUS_PORT)}/setup"


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
    """Serve the kid status page and parent setup on 127.0.0.1. Safe to call every controller cycle."""
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
    logging.info("Parent setup page: %s", setup_url(bound))
    try:
        write_html(app_dir)
    except Exception:
        logging.exception("Could not write status.html")
    return httpd, bound
