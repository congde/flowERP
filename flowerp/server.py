from __future__ import annotations

import json
import mimetypes
import os
import signal
import socket
import threading
import time
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

from flowerp import ERPService, ERPStore
from flowerp.models import DomainError, OrderLine
from flowerp.seed import load_ecommerce_sample
from flowerp.config import load_settings
from flowerp.operations import RuntimeCoordinator
from .api import APIRouter
from .http_bind import create_http_server


ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = (ROOT / "web").resolve()


def _structured_log(record: dict) -> None:
    """Best-effort structured logging must never break an HTTP response."""
    try:
        print(json.dumps(record, ensure_ascii=False), flush=True)
    except (BrokenPipeError, OSError, ValueError):
        # Detached Windows processes can lose their inherited stdout handle.
        # Dropping one log record is safer than aborting a valid HTTP request.
        return


class App:
    def __init__(self, runtime_dir: str | Path = ".runtime") -> None:
        runtime = Path(runtime_dir)
        self.settings = load_settings(runtime)
        self.store = ERPStore(runtime / "flowerp.db", self.settings.database_busy_timeout_ms)
        self.erp = ERPService(self.store)
        self.api = APIRouter(self.store, self.settings)


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "FlowERP/0.1"

        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(app.settings.request_timeout_seconds)

        def _json(self, status: int, body: object) -> None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self._response_request_id = f"REQ-{uuid.uuid4().hex.upper()}"
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Request-ID", self._response_request_id)
            self._security_headers()
            self.end_headers(); self.wfile.write(data)

        def _security_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
            )

        def _read_json(self) -> dict:
            content_type = self.headers.get("Content-Type", "")
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0:
                raise ValueError("Content-Length 无效")
            if length > app.settings.max_body_bytes:
                self.close_connection = True
                raise ValueError("请求体过大")
            raw = self.rfile.read(length) if length else b""
            if content_type and "application/json" not in content_type.lower():
                raise ValueError("写入接口只接受 application/json")
            return json.loads(raw.decode("utf-8")) if raw else {}

        def _v2(self, body: object = None) -> bool:
            if not urlparse(self.path).path.startswith("/api/v1/"):
                return False
            headers = {key.lower(): value for key, value in self.headers.items()}
            response = app.api.dispatch(self.command, self.path, headers, body or {}, self.client_address[0])
            if isinstance(response.body, str):
                data = response.body.encode("utf-8")
            else:
                data = json.dumps(response.body, ensure_ascii=False).encode("utf-8")
            self._response_request_id = response.headers.get("X-Request-ID", "")
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(data)))
            for key, value in response.headers.items(): self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD": self.wfile.write(data)
            return True

        def do_GET(self) -> None:  # noqa: N802
            if self._v2(): return
            path = urlparse(self.path).path
            try:
                if path.startswith("/api/"):
                    return self._json(410, {"error": "legacy_api_disabled", "message": "请使用 /api/v1"})
                if path == "/" or path.startswith("/static/") or path in {"/styles.css", "/app.js"}:
                    relative = "index.html" if path == "/" else path[1:] if path in {"/styles.css", "/app.js"} else path[len("/static/"):]
                    file_path = (WEB_ROOT / relative).resolve()
                    if WEB_ROOT not in file_path.parents or not file_path.is_file():
                        return self._json(404, {"error": "not_found"})
                    data = file_path.read_bytes(); self.send_response(200)
                    self.send_header("Content-Type", mimetypes.guess_type(file_path)[0] or "application/octet-stream")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-cache" if file_path.name == "index.html" else "public, max-age=3600")
                    self._security_headers(); self.end_headers(); self.wfile.write(data); return
                self._json(404, {"error": "not_found"})
            except (KeyError, DomainError, ValueError) as exc:
                self._json(400, {"error": type(exc).__name__, "message": str(exc)})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            try:
                body = self._read_json()
                if self._v2(body): return
                return self._json(410, {"error": "legacy_api_disabled", "message": "请使用 /api/v1"})
            except (TimeoutError, socket.timeout):
                self.close_connection = True
                self._json(408, {"error": "request_timeout", "message": "请求读取超时"})
            except (KeyError, DomainError, ValueError, json.JSONDecodeError) as exc:
                self._json(400, {"error": type(exc).__name__, "message": str(exc)})

        def do_PATCH(self) -> None:  # noqa: N802
            try: body = self._read_json()
            except (TimeoutError, socket.timeout):
                self.close_connection = True
                return self._json(408, {"error": "request_timeout", "message": "请求读取超时"})
            except (ValueError, json.JSONDecodeError) as exc: return self._json(400, {"error": type(exc).__name__, "message": str(exc)})
            if not self._v2(body): self._json(404, {"error": "not_found"})

        def do_OPTIONS(self) -> None:  # noqa: N802
            if not self._v2(): self._json(404, {"error": "not_found"})

        def log_message(self, fmt: str, *args: object) -> None:
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "level": "INFO",
                "event": "http_request",
                "request_id": getattr(self, "_response_request_id", ""),
                "remote_addr": self.client_address[0],
                "method": self.command,
                "path": self.path,
                "message": fmt % args,
            }
            _structured_log(record)

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8000, runtime_dir: str = ".runtime") -> None:
    app = App(runtime_dir)
    if host == "127.0.0.1" and app.settings.host != "127.0.0.1": host = app.settings.host
    if port == 8000 and app.settings.port != 8000: port = app.settings.port
    server = create_http_server(
        host,
        port,
        make_handler(app),
        service_name="FlowERP",
        retry_command=(
            "python -m flowerp serve --port 8080  "
            "（等价：python -X utf8 -m flowerp serve --port 8080）"
        ),
    )
    server.daemon_threads = False
    coordinator = RuntimeCoordinator(app.store)
    owner_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:12]}"
    lease = coordinator.acquire("sqlite-primary-writer", owner_id, 30)
    stop = threading.Event()

    def heartbeat() -> None:
        while not stop.wait(10):
            if not coordinator.renew("sqlite-primary-writer", owner_id, 30):
                _structured_log({"level": "CRITICAL", "event": "writer_lease_lost", "owner_id": owner_id})
                threading.Thread(target=server.shutdown, daemon=True).start()
                return

    heartbeat_thread = threading.Thread(target=heartbeat, name="flowerp-lease-heartbeat", daemon=True)
    heartbeat_thread.start()

    def request_shutdown(signum=None, frame=None) -> None:  # type: ignore[no-untyped-def]
        _structured_log({"level": "INFO", "event": "shutdown_requested", "signal": signum})
        threading.Thread(target=server.shutdown, daemon=True).start()

    if threading.current_thread() is threading.main_thread():
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            if hasattr(signal, name): signal.signal(getattr(signal, name), request_shutdown)
    _structured_log({"level": "INFO", "event": "server_started", "url": f"http://{host}:{port}",
                     "instance_id": owner_id, "fencing_token": lease["fencing_token"]})
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        stop.set()
        server.server_close()
        heartbeat_thread.join(timeout=2)
        try: app.store.checkpoint()
        finally: coordinator.release("sqlite-primary-writer", owner_id)
