"""Local stdio JSONL transport for TEP tool calls."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import TextIO

from .mcp_adapter import MCPAdapter
from .runtime import Runtime
from .storage import TEPHome


class TEPStdioApp:
    def __init__(self, adapter: MCPAdapter) -> None:
        self.adapter = adapter

    def handle_line(self, line: str) -> dict[str, object]:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": {"code": "invalid_json", "message": str(exc), "details": {}}}
        if not isinstance(payload, dict):
            return {"ok": False, "error": {"code": "invalid_request", "message": "request must be a JSON object", "details": {}}}
        if payload.get("method") == "tools/list":
            return {"ok": True, "tools": self.adapter.list_tools()}
        if payload.get("method") == "tools/call":
            params = payload.get("params", {})
            if not isinstance(params, dict):
                return {"ok": False, "error": {"code": "invalid_params", "message": "params must be a JSON object", "details": {}}}
            name = params.get("name")
            if not isinstance(name, str):
                return {"ok": False, "error": {"code": "missing_tool_name", "message": "params.name is required", "details": {}}}
            return self.adapter.call_tool(name, params.get("arguments", {}))
        return {
            "ok": False,
            "error": {
                "code": "unknown_method",
                "message": str(payload.get("method")),
                "details": {"supported": ["tools/list", "tools/call"]},
            },
        }


def make_stdio_app(tep_home: str | os.PathLike[str] = "~/.tep") -> TEPStdioApp:
    return TEPStdioApp(MCPAdapter(Runtime(TEPHome(tep_home))))


def run_loop(app: TEPStdioApp, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
    for line in stdin:
        if not line.strip():
            continue
        response = app.handle_line(line)
        stdout.write(json.dumps(response, sort_keys=True, separators=(",", ":")) + "\n")
        stdout.flush()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tep-stdio")
    parser.add_argument("--tep-home", default=os.environ.get("TEP_HOME", "~/.tep"))
    args = parser.parse_args(argv)
    run_loop(make_stdio_app(args.tep_home))


if __name__ == "__main__":
    main()
