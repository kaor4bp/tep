"""Standalone HTTP server for TEP tool calls."""

from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .mcp_adapter import MCPAdapter
from .runtime import Runtime
from .storage import TEPHome


class TEPHTTPApp:
    def __init__(self, adapter: MCPAdapter) -> None:
        self.adapter = adapter

    def handle(self, method: str, path: str, body: bytes = b"") -> tuple[int, dict[str, str], bytes]:
        if method == "GET" and path == "/health":
            return self._json(200, {"ok": True, "service": "tep-http"})
        if method == "GET" and path == "/tools":
            return self._json(200, {"ok": True, "tools": self.adapter.list_tools()})
        if method == "POST" and path == "/call":
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
            except json.JSONDecodeError as exc:
                return self._json(400, {"ok": False, "error": {"code": "invalid_json", "message": str(exc), "details": {}}})
            if not isinstance(payload, dict):
                return self._json(400, {"ok": False, "error": {"code": "invalid_request", "message": "request body must be a JSON object", "details": {}}})
            name = payload.get("name")
            if not isinstance(name, str):
                return self._json(400, {"ok": False, "error": {"code": "missing_tool_name", "message": "field 'name' is required", "details": {}}})
            result = self.adapter.call_tool(name, payload.get("arguments", {}))
            return self._json(200 if result.get("ok") else 400, result)
        return self._json(404, {"ok": False, "error": {"code": "not_found", "message": f"{method} {path}", "details": {}}})

    @staticmethod
    def _json(status: int, payload: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return status, {"content-type": "application/json; charset=utf-8", "content-length": str(len(body))}, body


def make_app(tep_home: str | os.PathLike[str] = "~/.tep") -> TEPHTTPApp:
    return TEPHTTPApp(MCPAdapter(Runtime(TEPHome(tep_home))))


def make_handler(app: TEPHTTPApp) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "TEPHTTP/0.1"

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
            self._dispatch()

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
            self._dispatch()

        def log_message(self, format: str, *args: Any) -> None:
            if os.environ.get("TEP_HTTP_ACCESS_LOG") == "1":
                super().log_message(format, *args)

        def _dispatch(self) -> None:
            length = int(self.headers.get("content-length", "0"))
            body = self.rfile.read(length) if length else b""
            status, headers, response = app.handle(self.command, self.path.split("?", 1)[0], body)
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(response)

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8765, tep_home: str | os.PathLike[str] = "~/.tep") -> None:
    app = make_app(tep_home)
    server = ThreadingHTTPServer((host, port), make_handler(app))
    print(f"tep-http listening on http://{host}:{port}", flush=True)
    server.serve_forever()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tep-http")
    parser.add_argument("--host", default=os.environ.get("TEP_HTTP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("TEP_HTTP_PORT", "8765")))
    parser.add_argument("--tep-home", default=os.environ.get("TEP_HOME", "~/.tep"))
    args = parser.parse_args(argv)
    serve(host=args.host, port=args.port, tep_home=args.tep_home)


if __name__ == "__main__":
    main()
