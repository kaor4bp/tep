#!/usr/bin/env python3
"""Conservative Codex hook adapter for the TEP v1 plugin."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
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


def tep_home(pointer: dict) -> Path:
    return Path(str(pointer.get("tep_home") or "~/.tep")).expanduser().resolve()


def repo_root() -> Path | None:
    env = os.environ.get("TEP_REPO_ROOT")
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env).expanduser())
    script = Path(__file__).resolve()
    candidates.extend([*script.parents, Path("/Users/kaor4bp/PycharmProjects/tep")])
    for candidate in candidates:
        root = candidate.resolve()
        if (root / "src" / "tep" / "runtime.py").exists():
            return root
    return None


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def project_root_matches(project: dict[str, Any], cwd: str | None) -> bool:
    if not cwd:
        return False
    try:
        current = Path(cwd).expanduser().resolve()
    except OSError:
        return False
    for raw_root in project.get("roots", []):
        try:
            root = Path(str(raw_root)).expanduser().resolve()
            current.relative_to(root)
            return True
        except (OSError, ValueError):
            continue
    return False


def project_ref_from_root(home: Path, cwd: str | None) -> str | None:
    for path in sorted((home / "registry" / "projects").glob("PRJ-*.json")):
        project = read_json(path)
        if project.get("status") == "archived":
            continue
        if project_root_matches(project, cwd):
            ref = project.get("id")
            return ref if isinstance(ref, str) and ref.startswith("PRJ-") else None
    return None


def workspace_for_project(home: Path, project_ref: str | None) -> str | None:
    if not project_ref:
        return None
    matches = []
    for path in sorted((home / "registry" / "workspaces").glob("WSP-*.json")):
        workspace = read_json(path)
        if workspace.get("status") == "archived":
            continue
        workspace_ref = workspace.get("id")
        if not isinstance(workspace_ref, str) or not workspace_ref.startswith("WSP-"):
            continue
        memberships = read_jsonl(home / "workspaces" / workspace_ref / "memberships" / "projects.jsonl")
        if any(row.get("active") is True and row.get("project_ref") == project_ref for row in memberships):
            matches.append(workspace_ref)
    return matches[0] if len(matches) == 1 else None


def resolve_workspace_ref(pointer: dict, cwd: str | None) -> str | None:
    value = workspace_ref()
    if value:
        return value
    home = tep_home(pointer)
    project_ref = pointer.get("project_ref")
    if not isinstance(project_ref, str) or not (home / "registry" / "projects" / f"{project_ref}.json").exists():
        project_ref = project_ref_from_root(home, cwd)
    return workspace_for_project(home, project_ref)


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


def call_local(pointer: dict, name: str, arguments: dict) -> bool:
    root = repo_root()
    if root is None:
        return False
    sys.path.insert(0, str(root / "src"))
    try:
        from tep import MCPAdapter, Runtime, TEPHome
    except ImportError:
        return call_local_subprocess(root, pointer, name, arguments)
    response = MCPAdapter(Runtime(TEPHome(str(tep_home(pointer))))).call_tool(name, arguments)
    return bool(response.get("ok"))


def call_local_subprocess(root: Path, pointer: dict, name: str, arguments: dict) -> bool:
    candidates = [
        os.environ.get("TEP_PYTHON"),
        "/tmp/tep-core-venv/bin/python",
        sys.executable,
        "python3",
    ]
    code = (
        "import json, sys; "
        "payload=json.load(sys.stdin); "
        "sys.path.insert(0, payload['repo_src']); "
        "from tep import MCPAdapter, Runtime, TEPHome; "
        "response=MCPAdapter(Runtime(TEPHome(payload['tep_home']))).call_tool(payload['name'], payload['arguments']); "
        "print(json.dumps({'ok': bool(response.get('ok'))}))"
    )
    payload = {
        "repo_src": str(root / "src"),
        "tep_home": str(tep_home(pointer)),
        "name": name,
        "arguments": arguments,
    }
    attempted: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in attempted:
            continue
        attempted.add(candidate)
        executable = Path(candidate).expanduser()
        if "/" in candidate and not executable.exists():
            continue
        try:
            completed = subprocess.run(
                [str(executable), "-c", code],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if completed.returncode != 0:
            continue
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError:
            continue
        if result.get("ok") is True:
            return True
    return False


def call_tep(pointer: dict, name: str, arguments: dict) -> bool:
    return call_http(pointer, name, arguments) or call_local(pointer, name, arguments)


def prompt_text(payload: dict) -> str:
    for key in ("prompt", "user_prompt", "userPrompt", "message", "text", "input"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("payload", "event", "body", "hook_input", "hookInput"):
        value = payload.get(key)
        if isinstance(value, dict):
            text = prompt_text(value)
            if text:
                return text
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
    if resolve_workspace_ref(pointer, payload.get("cwd")) is None:
        message += " No unique WSP-* resolved from .tep project membership; run tep-init or attach the project to one workspace."
    emit_context(message, event="SessionStart")
    return 0


def handle_user_prompt(payload: dict) -> int:
    _pointer_path, pointer = find_pointer(payload.get("cwd"))
    wsp = resolve_workspace_ref(pointer, payload.get("cwd"))
    text = prompt_text(payload)
    if pointer and wsp and text:
        call_tep(pointer, "capture_input", {"workspace_ref": wsp, "text": text, "input_class": "instruction"})
    return 0


def handle_pre_bash(payload: dict) -> int:
    command = command_text(payload)
    if command and DIRECT_TEP_WRITE.search(command):
        emit_deny("Direct writes to .tep storage are blocked; use typed TEP tools.")
    return 0


def handle_post_bash(payload: dict) -> int:
    _pointer_path, pointer = find_pointer(payload.get("cwd"))
    wsp = resolve_workspace_ref(pointer, payload.get("cwd"))
    command = command_text(payload)
    code = exit_code(payload)
    if pointer and wsp and command and code is not None:
        call_tep(
            pointer,
            "capture_bash_command",
            {
                "workspace_ref": wsp,
                "command": command,
                "cwd": str(payload.get("cwd") or ""),
                "exit_code": code,
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
