#!/usr/bin/env python3
"""Conservative Codex hook adapter for the TEP v1 plugin."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


TEP_MARKER = "TEP"
DIRECT_TEP_WRITE = re.compile(r"(^|[\s;&|])(?:cat|tee|python3?|node|perl|ruby|sed|cp|mv|rm|touch|mkdir)\b.*(?:~?/\.tep|/\.tep)(?:/|\s|$)")


def load_payload() -> dict:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def emit_context(message: str, *, event: str) -> None:
    print(
        json.dumps(
            {
                "systemMessage": f"{TEP_MARKER} {message}",
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "additionalContext": message,
                },
            }
        )
    )


def emit_deny(message: str) -> None:
    print(
        json.dumps(
            {
                "systemMessage": f"{TEP_MARKER} {message}",
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": message,
                },
            }
        )
    )


def find_pointer(cwd: str | None) -> tuple[Path | None, dict]:
    start = Path(cwd or os.getcwd()).expanduser().resolve()
    for candidate in [start, *start.parents]:
        path = candidate / ".tep"
        if not path.exists():
            continue
        try:
            return path, json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return path, {}
    return None, {}


def call_http(pointer: dict, name: str, arguments: dict) -> bool:
    server = str(pointer.get("mcp_server", ""))
    if not server.startswith(("http://", "https://")):
        return False
    body = json.dumps({"name": name, "arguments": arguments}).encode("utf-8")
    request = Request(server.rstrip("/") + "/call", data=body, headers={"content-type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return bool(payload.get("ok"))
    except (OSError, URLError, json.JSONDecodeError):
        return False


def prompt_text(payload: dict) -> str:
    for key in ("prompt", "user_prompt", "userPrompt", "message", "text", "input"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def command_text(payload: dict) -> str:
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict) and isinstance(tool_input.get("command"), str):
        return tool_input["command"].strip()
    if isinstance(payload.get("command"), str):
        return payload["command"].strip()
    return ""


def exit_code(payload: dict) -> int | None:
    for container_name in ("tool_response", "result", "response"):
        container = payload.get(container_name)
        if isinstance(container, dict) and isinstance(container.get("exit_code"), int):
            return container["exit_code"]
    return payload.get("exit_code") if isinstance(payload.get("exit_code"), int) else None


def workspace_ref() -> str | None:
    value = os.environ.get("TEP_WORKSPACE_REF")
    return value.strip() if value and value.strip().startswith("WSP-") else None


def handle_session_start(payload: dict) -> int:
    pointer_path, pointer = find_pointer(payload.get("cwd"))
    if pointer_path is None:
        emit_context("No local .tep pointer found. Run tep-init before relying on TEP hooks.", event="SessionStart")
        return 0
    message = "TEP hooks visible. Start by generating/continuing in-memory agent identity, then call brief_current_context."
    if not str(pointer.get("mcp_server", "")).startswith(("http://", "https://")):
        message += " Local pointer is not HTTP; standalone hook capture needs an HTTP TEP server or explicit stdio client."
    emit_context(message, event="SessionStart")
    return 0


def handle_user_prompt(payload: dict) -> int:
    _pointer_path, pointer = find_pointer(payload.get("cwd"))
    wsp = workspace_ref()
    text = prompt_text(payload)
    if pointer and wsp and text:
        call_http(pointer, "capture_input", {"workspace_ref": wsp, "text": text, "input_class": "user_instruction"})
    return 0


def handle_pre_bash(payload: dict) -> int:
    command = command_text(payload)
    if command and DIRECT_TEP_WRITE.search(command):
        emit_deny("Direct writes to .tep storage are blocked; use typed TEP tools.")
    return 0


def handle_post_bash(payload: dict) -> int:
    _pointer_path, pointer = find_pointer(payload.get("cwd"))
    wsp = workspace_ref()
    command = command_text(payload)
    if pointer and wsp and command:
        call_http(
            pointer,
            "capture_bash_command",
            {
                "workspace_ref": wsp,
                "command": command,
                "cwd": str(payload.get("cwd") or ""),
                "exit_code": exit_code(payload),
                "summary": "Captured by TEP Codex PostToolUse hook.",
            },
        )
    return 0


def handle_stop(payload: dict) -> int:
    if os.environ.get("TEP_AGENT_REF") and workspace_ref():
        emit_context("Before final answer/task done, call final_answer_preflight or task_done_preflight with selected support refs.", event="Stop")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    event = argv[0] if argv else ""
    payload = load_payload()
    handlers = {
        "session-start": handle_session_start,
        "user-prompt": handle_user_prompt,
        "pre-bash": handle_pre_bash,
        "post-bash": handle_post_bash,
        "stop": handle_stop,
    }
    handler = handlers.get(event)
    if handler is None:
        return 0
    return handler(payload)


if __name__ == "__main__":
    raise SystemExit(main())
