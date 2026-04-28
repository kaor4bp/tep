"""Minimal MCP stdio server for TEP tools.

This module intentionally avoids an MCP SDK dependency. It implements the small
JSON-RPC surface Codex needs for stdio tools: initialize, notifications, list,
and call.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from typing import Any, BinaryIO, TextIO

from .mcp_adapter import MCPAdapter
from .runtime import Runtime
from .storage import TEPHome


SERVER_VERSION = "0.6.21"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"


JsonObject = dict[str, Any]


def _property_schema(name: str) -> JsonObject:
    if name in {"exit_code", "limit", "max_chars"}:
        return {"type": "integer"}
    if name in {"goals", "support_refs", "project_refs", "task_refs", "source_refs", "evidence_refs", "contradiction_refs", "roots", "aliases", "done_criteria"}:
        return {"type": "array", "items": {"type": "string"}}
    if name == "candidates":
        return {"type": "array", "items": {"type": "object", "additionalProperties": True}}
    if name in {"identity", "settings", "action", "scope", "synced_object", "bridge_limits"}:
        return {"type": "object", "additionalProperties": True}
    if name == "allow_create":
        return {"type": "boolean"}
    return {"type": "string"}


def _tool_schema(tool: JsonObject) -> JsonObject:
    required = list(tool.get("required", []))
    optional = list(tool.get("optional", []))
    properties = {name: _property_schema(name) for name in [*required, *optional]}
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": True,
    }


def mcp_tools(adapter: MCPAdapter) -> list[JsonObject]:
    tools = []
    for tool in adapter.list_tools():
        tools.append(
            {
                "name": tool["name"],
                "description": tool["description"],
                "inputSchema": _tool_schema(tool),
            }
        )
    return tools


def response(message_id: Any, result: JsonObject | None = None, error: JsonObject | None = None) -> JsonObject:
    payload: JsonObject = {"jsonrpc": "2.0", "id": message_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result or {}
    return payload


def method_not_found(message_id: Any, method: str) -> JsonObject:
    return response(message_id, error={"code": -32601, "message": f"Method not found: {method}"})


def invalid_request(message_id: Any, message: str) -> JsonObject:
    return response(message_id, error={"code": -32600, "message": message})


class TEPMCPStdioServer:
    def __init__(self, adapter: MCPAdapter, *, protocol_version: str = DEFAULT_PROTOCOL_VERSION) -> None:
        self.adapter = adapter
        self.protocol_version = protocol_version

    def handle_message(self, message: JsonObject) -> JsonObject | None:
        message_id = message.get("id")
        method = str(message.get("method", ""))
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return invalid_request(message_id, "params must be an object")

        if method == "initialize":
            requested_version = str(params.get("protocolVersion") or self.protocol_version)
            return response(
                message_id,
                {
                    "protocolVersion": requested_version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "tep", "version": SERVER_VERSION},
                },
            )

        if method.startswith("notifications/"):
            return None

        if method == "tools/list":
            return response(message_id, {"tools": mcp_tools(self.adapter)})

        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(name, str):
                return invalid_request(message_id, "tools/call params.name is required")
            if not isinstance(arguments, dict):
                return invalid_request(message_id, "tools/call params.arguments must be an object")
            result = self.adapter.call_tool(name, arguments)
            text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
            return response(
                message_id,
                {
                    "content": [{"type": "text", "text": text}],
                    "isError": not bool(result.get("ok")),
                },
            )

        return method_not_found(message_id, method)


def emit(message: JsonObject | list[JsonObject], stdout: TextIO = sys.stdout, *, framed: bool = False) -> None:
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    if framed:
        body = payload.encode("utf-8")
        stdout.write(f"Content-Length: {len(body)}\r\n\r\n{payload}")
    else:
        stdout.write(payload + "\n")
    stdout.flush()


def emit_bytes(message: JsonObject | list[JsonObject], stdout: BinaryIO = sys.stdout.buffer, *, framed: bool = False) -> None:
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if framed:
        stdout.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
    else:
        stdout.write(body + b"\n")
    stdout.flush()


def handle_decoded_message(server: TEPMCPStdioServer, message: Any) -> JsonObject | list[JsonObject] | None:
    messages = message if isinstance(message, list) else [message]
    results: list[JsonObject] = []
    for item in messages:
        if not isinstance(item, dict):
            results.append(invalid_request(None, "message must be an object"))
            continue
        try:
            result = server.handle_message(item)
        except Exception as exc:  # noqa: BLE001 - stdio MCP must not die on one bad tool call.
            traceback.print_exc(file=sys.stderr)
            result = response(item.get("id"), error={"code": -32603, "message": f"Internal error: {exc}"})
        if result is not None:
            results.append(result)
    if isinstance(message, list):
        return results or None
    return results[0] if results else None


def run_loop(server: TEPMCPStdioServer, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
    while True:
        line = stdin.readline()
        if line == "":
            break
        line = line.strip()
        if not line:
            continue
        framed = line.casefold().startswith("content-length:")
        try:
            if framed:
                length = int(line.split(":", 1)[1].strip())
                while True:
                    header = stdin.readline()
                    if header in {"", "\n", "\r\n"}:
                        break
                raw_message = stdin.read(length)
            else:
                raw_message = line
            message = json.loads(raw_message)
        except json.JSONDecodeError as exc:
            emit(response(None, error={"code": -32700, "message": f"Parse error: {exc}"}), stdout, framed=framed)
            continue
        except (OSError, ValueError) as exc:
            emit(response(None, error={"code": -32600, "message": f"Invalid MCP frame: {exc}"}), stdout, framed=framed)
            continue
        result = handle_decoded_message(server, message)
        if result is not None:
            emit(result, stdout, framed=framed)


def run_loop_binary(server: TEPMCPStdioServer, stdin: BinaryIO = sys.stdin.buffer, stdout: BinaryIO = sys.stdout.buffer) -> None:
    while True:
        line = stdin.readline()
        if line == b"":
            break
        line = line.strip()
        if not line:
            continue
        framed = line.lower().startswith(b"content-length:")
        try:
            if framed:
                length = int(line.split(b":", 1)[1].strip())
                while True:
                    header = stdin.readline()
                    if header in {b"", b"\n", b"\r\n"}:
                        break
                raw_message = stdin.read(length).decode("utf-8")
            else:
                raw_message = line.decode("utf-8")
            message = json.loads(raw_message)
        except json.JSONDecodeError as exc:
            emit_bytes(response(None, error={"code": -32700, "message": f"Parse error: {exc}"}), stdout, framed=framed)
            continue
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            emit_bytes(response(None, error={"code": -32600, "message": f"Invalid MCP frame: {exc}"}), stdout, framed=framed)
            continue
        result = handle_decoded_message(server, message)
        if result is not None:
            emit_bytes(result, stdout, framed=framed)


def make_mcp_server(tep_home: str | os.PathLike[str] = "~/.tep") -> TEPMCPStdioServer:
    return TEPMCPStdioServer(MCPAdapter(Runtime(TEPHome(tep_home))))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tep-mcp")
    parser.add_argument("--tep-home", default=os.environ.get("TEP_HOME", "~/.tep"))
    args = parser.parse_args(argv)
    run_loop_binary(make_mcp_server(args.tep_home))


if __name__ == "__main__":
    main()
