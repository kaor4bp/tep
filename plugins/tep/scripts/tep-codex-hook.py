#!/usr/bin/env python3
"""Soft Codex hooks for the TEP 0.12 server."""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main(argv: list[str]) -> int:
    event = argv[1] if len(argv) > 1 else ""
    payload = _read_payload()
    if event == "user-prompt":
        return _handle_user_prompt(payload)
    if event == "pre-bash":
        return _handle_pre_bash(payload)
    if event == "stop":
        return _handle_stop(payload)
    _emit({})
    return 0


def _handle_pre_bash(payload: dict[str, Any]) -> int:
    command = _command_text(payload)
    if not command:
        _emit({})
        return 0
    policy = ((_call_tep("hook_policy", {}) or {}).get("data") or {})
    is_capture_run = _is_capture_run_command(command)
    if policy.get("blocked_by_jobs") and not is_capture_run:
        _deny(str(policy.get("deny_reason") or "TEP has too many pending jobs. Resolve jobs or relax settings before running Bash."))
        return 0
    mode = str(policy.get("pretooluse_bash_mode") or "warn")
    if mode == "require_capture_run" and not is_capture_run:
        _deny(f"TEP settings require Bash through capture_run. Use `{_client_hint()} run-capture --cwd . -- <command>` or relax PreToolUse mode in TEP UI.")
        return 0
    if mode == "warn" and not is_capture_run:
        client = _client_hint()
        _emit(
            {
                "systemMessage": f"TEP: consider `{client} run-capture --cwd . -- <command>` so stdout/stderr become src_* evidence and learning pressure is computed.",
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": "TEP bash mode is warn; raw Bash is allowed but capture_run gives digest, suggested CLM, and DAG pressure.",
                },
            }
        )
        return 0
    _emit({})
    return 0


def _handle_user_prompt(payload: dict[str, Any]) -> int:
    text = _prompt_text(payload)
    if not text:
        _emit({})
        return 0
    result = _call_tep(
        "capture_input",
        {
            "text": text,
            "input_class": _input_class(text),
            "origin": {
                "kind": "codex_hook",
                "hook_event": "UserPromptSubmit",
                "cwd": _cwd(payload),
            },
        },
    )
    ref = ((result or {}).get("data") or {}).get("id")
    if isinstance(ref, str):
        _emit(
            {
                "systemMessage": f"TEP captured user input as {ref}. Use brief/search_facts before creating new CLM facts.",
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": f"TEP input_ref={ref}. User input is durable; extract reusable facts only when needed.",
                },
            }
        )
    else:
        _emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": "TEP input capture was skipped because the server was unavailable.",
                }
            }
        )
    return 0


def _handle_stop(payload: dict[str, Any]) -> int:
    # Codex currently rejects some Stop hook JSON shapes that are valid for
    # other hook events. Keep Stop non-blocking and non-injective; TEP pressure
    # is surfaced through brief, skill guidance, and PreToolUse.
    _emit({})
    return 0


def _read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _prompt_text(payload: dict[str, Any]) -> str:
    for key in ("prompt", "user_prompt", "userPrompt", "message", "text", "input"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("payload", "event", "body", "hook_input", "hookInput"):
        value = payload.get(key)
        if isinstance(value, dict):
            nested = _prompt_text(value)
            if nested:
                return nested
    return ""


def _cwd(payload: dict[str, Any]) -> str | None:
    for key in ("cwd", "workspace", "workspaceRoot", "workspace_root"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return os.getcwd()


def _command_text(payload: dict[str, Any]) -> str:
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        value = tool_input.get("command")
        if isinstance(value, str):
            return value.strip()
    for key in ("command", "cmd"):
        value = payload.get(key)
        if isinstance(value, str):
            return value.strip()
    return ""


def _is_capture_run_command(command: str) -> bool:
    compact = " ".join(command.split()).casefold()
    return "tep-client run-capture" in compact or "/tep-client run-capture" in compact or "tep.server_client" in compact and " run-capture" in compact


def _client_hint() -> str:
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tep-client")
    return script if os.path.exists(script) else "python3 -m tep.server_client"


def _input_class(text: str) -> str:
    folded = text.casefold()
    if any(marker in folded for marker in ("запомни", "remember", "важно", "important")):
        return "provided_context"
    if "?" in text or folded.startswith(("что ", "как ", "why ", "how ", "what ")):
        return "question"
    return "instruction"


def _call_tep(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    server_url = os.environ.get("TEP_SERVER_URL", "http://127.0.0.1:8765").rstrip("/")
    body = json.dumps({"name": name, "arguments": arguments}, ensure_ascii=False).encode("utf-8")
    request = Request(server_url + "/call", data=body, headers={"content-type": "application/json"}, method="POST")
    for attempt in range(3):
        if attempt:
            time.sleep(0.2 * attempt)
        try:
            with urlopen(request, timeout=3) as response:  # noqa: S310 - local/private server.
                decoded = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
            continue
        return decoded if isinstance(decoded, dict) and decoded.get("ok") else None
    return None


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _deny(message: str) -> None:
    _emit(
        {
            "systemMessage": message,
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": message,
            },
        }
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
