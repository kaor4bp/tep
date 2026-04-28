#!/usr/bin/env python3
"""Conservative Codex hook adapter for the TEP v1 plugin."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


TEP_MARKER = "TEP"
DIRECT_TEP_WRITE = re.compile(r"(^|[\s;&|])(?:cat|tee|python3?|node|perl|ruby|sed|cp|mv|rm|touch|mkdir)\b.*(?:~?/\.tep|/\.tep)(?:/|\s|$)")
DEFAULT_SETTINGS = {
    "version": 1,
    "enforcement": {
        "mode": "balanced",
        "session_start_requires_frame": False,
        "bash_policy": "act_for_evidence",
        "edit_policy": "act_required",
        "final_policy": "preflight_required",
        "unknown_action_policy": "block_until_act",
        "act_timeout_seconds": 3600,
        "context_requirements": {},
    },
}
CONTEXT_KINDS = ("task_briefing", "coding_guidelines", "domain_theory", "project_conventions")
READ_ONLY_BASH = re.compile(
    r"^\s*(?:pwd|ls(?:\s|$)|find(?:\s|$)|rg(?:\s|$)|grep(?:\s|$)|sed\s+-n(?:\s|$)|cat(?:\s|$)|"
    r"head(?:\s|$)|tail(?:\s|$)|wc(?:\s|$)|nl(?:\s|$)|git\s+(?:status|diff|log|show|branch)(?:\s|$)|test\s+[-a-zA-Z](?:\s|$))"
)
EVIDENCE_BASH = re.compile(
    r"(^|[\s;&|])(?:pytest|tox|coverage|npm\s+test|pnpm\s+test|yarn\s+test|make\s+test|"
    r"python3?\s+-m\s+(?:pytest|unittest)|uv\s+run\s+pytest|cargo\s+test|go\s+test)(?:\s|$)"
)
MUTATION_BASH = re.compile(
    r"(^|[\s;&|])(?:rm|mv|cp|mkdir|touch|chmod|chown|git\s+(?:add|commit|push|reset|checkout|merge|rebase)|"
    r"pip\s+install|python3?\s+-m\s+pip\s+install|npm\s+install|pnpm\s+install|yarn\s+add)(?:\s|$)|(?:>|>>)"
)


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


def merge_settings(*records: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(DEFAULT_SETTINGS))
    for record in records:
        deep_update(result, record)
    return result


def deep_update(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_update(target[key], value)
        else:
            target[key] = value


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
    matches: list[tuple[str, str, int, str]] = []
    for path in sorted((home / "registry" / "workspaces").glob("WSP-*.json")):
        workspace = read_json(path)
        if workspace.get("status") == "archived":
            continue
        workspace_ref = workspace.get("id")
        if not isinstance(workspace_ref, str) or not workspace_ref.startswith("WSP-"):
            continue
        memberships = read_jsonl(home / "workspaces" / workspace_ref / "memberships" / "projects.jsonl")
        rows = [row for row in memberships if row.get("active") is True and row.get("project_ref") == project_ref]
        if rows:
            latest_membership = max(str(row.get("added_at", "")) for row in rows)
            membership_path = home / "workspaces" / workspace_ref / "memberships" / "projects.jsonl"
            try:
                mtime_ns = membership_path.stat().st_mtime_ns
            except OSError:
                mtime_ns = 0
            matches.append((latest_membership, str(workspace.get("created_at", "")), mtime_ns, workspace_ref))
    if not matches:
        return None
    matches.sort(reverse=True)
    return matches[0][3]


def resolve_workspace_ref(pointer: dict, cwd: str | None) -> str | None:
    value = workspace_ref()
    if value:
        return value
    home = tep_home(pointer)
    project_ref = pointer.get("project_ref")
    if not isinstance(project_ref, str) or not (home / "registry" / "projects" / f"{project_ref}.json").exists():
        project_ref = project_ref_from_root(home, cwd)
    return workspace_for_project(home, project_ref)


def read_settings_for(pointer: dict, workspace: str | None) -> dict[str, Any]:
    home = tep_home(pointer)
    global_settings = read_json(home / "settings.json")
    workspace_settings = read_json(home / "workspaces" / workspace / "settings.json") if workspace else {}
    return merge_settings(global_settings, workspace_settings)


def classify_bash(command: str) -> str:
    if not command:
        return "unknown"
    if MUTATION_BASH.search(command):
        return "mutation"
    if EVIDENCE_BASH.search(command):
        return "evidence_producing"
    if READ_ONLY_BASH.search(command):
        return "read_only_context"
    return "unknown"


def open_act_ref(pointer: dict, workspace: str | None, settings: dict[str, Any] | None = None) -> str | None:
    explicit = os.environ.get("TEP_OPEN_ACT_REF")
    if explicit and explicit.startswith("L-"):
        return explicit
    agent_ref = os.environ.get("TEP_AGENT_REF")
    if not workspace:
        return None
    home = tep_home(pointer)
    timeout = int((settings or DEFAULT_SETTINGS).get("enforcement", {}).get("act_timeout_seconds", 3600))
    if agent_ref:
        return open_act_in_ledger(home / "workspaces" / workspace / "agents" / agent_ref / "ledger.jsonl", timeout_seconds=timeout)
    open_refs = []
    for ledger_path in sorted((home / "workspaces" / workspace / "agents").glob("AGENT-*/ledger.jsonl")):
        open_ref = open_act_in_ledger(ledger_path, timeout_seconds=timeout)
        if open_ref:
            open_refs.append(open_ref)
    unique = sorted(set(open_refs))
    return unique[0] if len(unique) == 1 else None


def open_act_in_ledger(ledger_path: Path, *, timeout_seconds: int = 3600) -> str | None:
    rows = read_jsonl(ledger_path)
    open_ref = None
    open_created_at = None
    for row in rows:
        if row.get("kind") == "act":
            open_ref = row.get("id")
            open_created_at = row.get("created_at")
        elif row.get("kind") == "close_act":
            open_ref = None
            open_created_at = None
    if not isinstance(open_ref, str) or not isinstance(open_created_at, str):
        return None
    try:
        opened = datetime.fromisoformat(open_created_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if int((datetime.now(UTC) - opened).total_seconds()) >= timeout_seconds:
        return None
    return open_ref


def active_task_ref(pointer: dict, workspace: str | None) -> str | None:
    explicit = os.environ.get("TEP_TASK_REF")
    if explicit and explicit.startswith("TASK-"):
        return explicit
    agent_ref = os.environ.get("TEP_AGENT_REF")
    if not workspace:
        return None
    home = tep_home(pointer)
    agents = []
    if agent_ref:
        agents.append(read_json(home / "workspaces" / workspace / "agents" / agent_ref / "agent.json"))
    else:
        agents.extend(read_json(path) for path in sorted((home / "workspaces" / workspace / "agents").glob("AGENT-*/agent.json")))
    task_refs = []
    for agent in agents:
        path = agent.get("working_context", {}).get("active_task_path", [])
        if path:
            task_refs.append(path[-1])
    unique = sorted({ref for ref in task_refs if isinstance(ref, str) and ref.startswith("TASK-")})
    return unique[0] if len(unique) == 1 else None


def required_context_kinds(settings: dict[str, Any]) -> list[str]:
    enforcement = settings.get("enforcement", {})
    mode = enforcement.get("mode", "balanced")
    if mode == "strict":
        defaults = {kind: "required" for kind in CONTEXT_KINDS}
    elif mode == "off":
        defaults = {kind: "disabled" for kind in CONTEXT_KINDS}
    elif mode == "balanced":
        defaults = {
            "task_briefing": "required",
            "coding_guidelines": "on_demand",
            "domain_theory": "on_demand",
            "project_conventions": "on_demand",
        }
    else:
        defaults = {kind: "on_demand" for kind in CONTEXT_KINDS}
    defaults.update(enforcement.get("context_requirements", {}))
    return [kind for kind in CONTEXT_KINDS if defaults.get(kind) == "required"]


def active_context_packs(pointer: dict, workspace: str, task_ref: str) -> list[dict[str, Any]]:
    home = tep_home(pointer)
    workspace_dir = home / "workspaces" / workspace
    task = read_json(workspace_dir / "tasks" / f"{task_ref}.json")
    project_refs = task.get("project_refs", [])
    if not isinstance(project_refs, list):
        project_refs = []
    base = workspace_dir / "artifacts" / "context_packs"
    paths = list((base / "tasks" / task_ref).glob("CTX-*.json"))
    paths.extend((base / "global").glob("CTX-*.json"))
    for project_ref in project_refs:
        if isinstance(project_ref, str) and project_ref.startswith("PRJ-"):
            paths.extend((base / "projects" / project_ref).glob("CTX-*.json"))
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(paths):
        record = read_json(path)
        record_id = record.get("id")
        if record.get("status") != "active" or not isinstance(record_id, str) or record_id in seen:
            continue
        seen.add(record_id)
        records.append(record)
    return records


def context_kind_satisfied(kind: str, records: list[dict[str, Any]]) -> bool:
    for record in records:
        if record.get("kind") != kind:
            continue
        if kind == "task_briefing" and record.get("scope_type") != "task":
            continue
        return True
    return False


def missing_task_context(pointer: dict, workspace: str | None, task_ref: str | None, settings: dict[str, Any]) -> list[str]:
    if not workspace or not task_ref:
        return []
    required = required_context_kinds(settings)
    if not required:
        return []
    active = active_context_packs(pointer, workspace, task_ref)
    return [kind for kind in required if not context_kind_satisfied(kind, active)]


def bash_pressure(settings: dict[str, Any], classification: str, act_ref: str | None) -> dict[str, Any]:
    enforcement = settings.get("enforcement", {})
    mode = enforcement.get("mode", "balanced")
    policy = enforcement.get("bash_policy", "act_for_evidence")
    unknown_policy = enforcement.get("unknown_action_policy", "block_until_act")
    required = False
    if mode != "off":
        if policy == "act_for_all":
            required = True
        elif policy == "act_for_evidence":
            required = classification in {"evidence_producing", "mutation"} or (classification == "unknown" and unknown_policy == "block_until_act")
    blocked = required and act_ref is None and mode in {"balanced", "strict"}
    return {
        "mode": mode,
        "bash_policy": policy,
        "classification": classification,
        "act_required": required,
        "blocked": blocked,
        "open_act": act_ref,
    }


def call_http(pointer: dict, name: str, arguments: dict) -> dict[str, Any] | None:
    server = str(pointer.get("mcp_server", ""))
    if not server.startswith(("http://", "https://")):
        return None
    body = json.dumps({"name": name, "arguments": arguments}).encode("utf-8")
    request = Request(server.rstrip("/") + "/call", data=body, headers={"content-type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, URLError, json.JSONDecodeError):
        return None


def call_local(pointer: dict, name: str, arguments: dict) -> dict[str, Any] | None:
    root = repo_root()
    if root is None:
        return None
    sys.path.insert(0, str(root / "src"))
    try:
        from tep import MCPAdapter, Runtime, TEPHome
    except ImportError:
        return call_local_subprocess(root, pointer, name, arguments)
    response = MCPAdapter(Runtime(TEPHome(str(tep_home(pointer))))).call_tool(name, arguments)
    return response


def call_local_subprocess(root: Path, pointer: dict, name: str, arguments: dict) -> dict[str, Any] | None:
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
        "print(json.dumps(response))"
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
        if isinstance(result, dict):
            return result
    return None


def call_tep(pointer: dict, name: str, arguments: dict) -> dict[str, Any] | None:
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


def response_text(payload: dict, stream: str) -> str:
    keys = {
        "stdout": ("stdout", "output"),
        "stderr": ("stderr", "error_output"),
    }[stream]
    for container_name in ("tool_response", "result", "response"):
        container = payload.get(container_name)
        if not isinstance(container, dict):
            continue
        for key in keys:
            value = container.get(key)
            if isinstance(value, str):
                return value
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def compact_command(command: str, limit: int = 160) -> str:
    compact = " ".join(command.split())
    if len(compact) > limit:
        compact = compact[: limit - 3] + "..."
    return compact


def first_meaningful_output_line(output: str) -> str:
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if set(stripped) <= {"=", "-", "_", "."}:
            continue
        return stripped[:220]
    return ""


def pytest_summary(output: str) -> tuple[str | None, list[str]]:
    summary = None
    failed: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        match = re.search(r"=+\s*(?P<summary>.*?(?:failed|passed|error|errors|skipped|xfailed|xpassed|deselected).*?)\s+in\s+[0-9.]+s\s*=+", stripped)
        if match:
            summary = " ".join(match.group("summary").split())
        if stripped.startswith("FAILED "):
            failed.append(stripped.removeprefix("FAILED ").split(" - ", 1)[0][:180])
    return summary, failed[:5]


def is_pytest_command(command: str) -> bool:
    return bool(re.search(r"(^|\s)(pytest|py\.test)(\s|$)", command) or " pytest " in f" {command} ")


def pytest_failure_claims(command: str, output: str, limit: int = 10) -> list[str]:
    compact = compact_command(command)
    claims: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        match = re.match(r"(?P<status>FAILED|ERROR)\s+(?P<target>\S+)(?:\s+-\s+(?P<reason>.*))?$", stripped)
        if not match:
            continue
        target = match.group("target")[:180]
        reason = " ".join((match.group("reason") or "").split())[:220]
        status = "failed" if match.group("status") == "FAILED" else "errored"
        statement = f"Pytest test `{target}` {status} during `{compact}`."
        if reason:
            statement = statement[:-1] + f": {reason}."
        claims.append(statement)
        if len(claims) >= limit:
            break
    return claims


def command_observation_statement(command: str, code: int, stdout: str = "", stderr: str = "") -> str:
    compact = compact_command(command)
    combined = "\n".join(part for part in [stdout, stderr] if part)
    if is_pytest_command(command):
        summary, failed = pytest_summary(combined)
        if summary:
            statement = f"Pytest command `{compact}` completed with exit code {code}: {summary}."
            if failed:
                statement += " Failed tests: " + "; ".join(failed) + "."
            return statement
    first_line = first_meaningful_output_line(combined)
    if first_line:
        return f"Command `{compact}` exited with code {code}; first output line: {first_line}"
    return f"Command `{compact}` exited with code {code}."


def should_create_command_summary_claim(command: str, code: int, stdout: str = "", stderr: str = "") -> bool:
    if not is_pytest_command(command):
        return False
    summary, failed = pytest_summary("\n".join(part for part in [stdout, stderr] if part))
    return bool(summary and (code != 0 or failed))


def workspace_ref() -> str | None:
    value = os.environ.get("TEP_WORKSPACE_REF")
    return value.strip() if value and value.strip().startswith("WSP-") else None


def handle_session_start(payload: dict) -> int:
    pointer_path, pointer = find_pointer(payload.get("cwd"))
    if pointer_path is None:
        emit_context("No local .tep pointer found. Run tep-init before relying on TEP hooks.", event="SessionStart")
        return 0
    message = (
        "TEP hooks visible. Start by generating/continuing in-memory agent identity, "
        "then call brief_current_context. During the task, record durable system facts as CLM-* when observations change your understanding."
    )
    wsp = resolve_workspace_ref(pointer, payload.get("cwd"))
    if wsp is None:
        message += " No unique WSP-* resolved from .tep project membership; run tep-init or attach the project to one workspace."
    else:
        settings = read_settings_for(pointer, wsp)
        enforcement = settings.get("enforcement", {})
        message += f" Enforcement mode={enforcement.get('mode')} bash_policy={enforcement.get('bash_policy')}."
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
    pointer_path, pointer = find_pointer(payload.get("cwd"))
    if pointer_path is None or not command:
        return 0
    wsp = resolve_workspace_ref(pointer, payload.get("cwd"))
    settings = read_settings_for(pointer, wsp)
    missing_context = missing_task_context(pointer, wsp, active_task_ref(pointer, wsp), settings)
    if missing_context:
        emit_deny(
            "Task work is blocked until required TEP context packs exist. "
            f"missing_context={','.join(missing_context)}. "
            "Use lookup_facts and compile_context_pack before running task-bound Bash."
        )
        return 0
    pressure = bash_pressure(settings, classify_bash(command), open_act_ref(pointer, wsp, settings))
    if pressure["blocked"]:
        emit_deny(
            "Bash action is blocked by TEP enforcement settings. "
            f"classification={pressure['classification']} policy={pressure['bash_policy']}. "
            "Open an ACT with open_probe, then call protected_action_preflight before running this command."
        )
    elif pressure["act_required"]:
        prefix = "Bash action is ACT-bound before execution." if pressure["open_act"] else "Bash action should be bound to an open ACT before execution."
        emit_context(
            f"{prefix} "
            f"classification={pressure['classification']} policy={pressure['bash_policy']}.",
            event="PreToolUse",
        )
    return 0


def handle_post_bash(payload: dict) -> int:
    _pointer_path, pointer = find_pointer(payload.get("cwd"))
    wsp = resolve_workspace_ref(pointer, payload.get("cwd"))
    command = command_text(payload)
    code = exit_code(payload)
    if pointer and wsp and command and code is not None:
        stdout = response_text(payload, "stdout")
        stderr = response_text(payload, "stderr")
        captured = call_tep(
            pointer,
            "capture_bash_command",
            {
                "workspace_ref": wsp,
                "command": command,
                "cwd": str(payload.get("cwd") or ""),
                "exit_code": code,
                "stdout": stdout,
                "stderr": stderr,
            },
        )
        run = captured.get("data", {}).get("run") if isinstance(captured, dict) and captured.get("ok") else None
        if not isinstance(run, dict):
            return 0
        statement = command_observation_statement(command, code, stdout=stdout, stderr=stderr)
        source_response = None
        if stdout:
            source_response = call_tep(pointer, "capture_run_output_source", {"workspace_ref": wsp, "run_ref": run["id"], "stream": "stdout"})
        elif stderr:
            source_response = call_tep(pointer, "capture_run_output_source", {"workspace_ref": wsp, "run_ref": run["id"], "stream": "stderr"})
        else:
            source_response = call_tep(
                pointer,
                "create_source",
                {
                    "workspace_ref": wsp,
                    "source_kind": "command_summary",
                    "quote": statement,
                    "classification": {
                        "input_class": "observation",
                        "source_class": "runtime_observation",
                        "document_kind": "command_summary",
                        "evidence_role": "observation",
                        "authority_scope": "local_runtime",
                        "independence_key": f"run:{run['id']}",
                    },
                    "origin": {"kind": "command", "ref": run["id"]},
                    "provenance": {
                        "entity_ref": run["id"],
                        "activity_ref": run["id"],
                        "responsible_agent": run.get("agent_ref") or "runtime",
                        "content_hash": run.get("content_hash"),
                        "locator": f"{run['id']}:summary",
                        "quote_span": None,
                        "retrieved_at": None,
                        "published_at": None,
                    },
                    "critique_status": "audited",
                },
            )
        source = source_response.get("data", {}).get("source") if isinstance(source_response, dict) and source_response.get("ok") else None
        if isinstance(source, dict):
            project_ref = pointer.get("project_ref")
            created_claims = 0
            if should_create_command_summary_claim(command, code, stdout=stdout, stderr=stderr):
                payload_args = {"workspace_ref": wsp, "statement": statement, "source_refs": [source["id"]]}
                if isinstance(project_ref, str) and project_ref.startswith("PRJ-"):
                    payload_args["project_refs"] = [project_ref]
                response = call_tep(pointer, "create_claim", payload_args)
                if isinstance(response, dict) and response.get("ok"):
                    created_claims += 1
            combined = "\n".join(part for part in [stdout, stderr] if part)
            for detail_statement in pytest_failure_claims(command, combined):
                detail_args = {"workspace_ref": wsp, "statement": detail_statement, "source_refs": [source["id"]]}
                if isinstance(project_ref, str) and project_ref.startswith("PRJ-"):
                    detail_args["project_refs"] = [project_ref]
                response = call_tep(pointer, "create_claim", detail_args)
                if isinstance(response, dict) and response.get("ok"):
                    created_claims += 1
            if created_claims:
                emit_context(
                    f"Captured RUN/SRC and {created_claims} narrow observation CLM. If this changes your model of the system, create separate system-behavior CLM-* facts and link them to the observation.",
                    event="PostToolUse",
                )
            else:
                if classify_bash(command) == "evidence_producing":
                    emit_context(
                        f"Captured RUN/SRC for evidence-producing command as {run['id']}. Extract quote-backed facts with extract_run_claim_candidates, then create atomic CLM-* with create_claim_from_evidence. Ask: what did this test output teach about system behavior, contracts, failure modes, or constraints?",
                        event="PostToolUse",
                    )
                    return 0
                emit_context(
                    "Captured RUN/SRC only. Do not create a mechanical command CLM; create CLM-* only if you learned a system fact from this observation.",
                    event="PostToolUse",
                )
    return 0


def handle_stop(payload: dict) -> int:
    if os.environ.get("TEP_AGENT_REF") and workspace_ref():
        emit_context(
            "Before final answer/task done, record any newly learned durable system facts as CLM-* with SRC support, then call final_answer_preflight or task_done_preflight with selected support refs.",
            event="Stop",
        )
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
