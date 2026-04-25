"""Runtime enforcement settings and action classification."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .errors import ValidationError
from .responses import move


CONTEXT_KINDS = ("task_briefing", "coding_guidelines", "domain_theory", "project_conventions")
CONTEXT_REQUIREMENT_LEVELS = {"required", "on_demand", "optional", "disabled"}

DEFAULT_SETTINGS: dict[str, Any] = {
    "version": 1,
    "enforcement": {
        "mode": "balanced",
        "session_start_requires_frame": False,
        "bash_policy": "act_for_evidence",
        "edit_policy": "act_required",
        "final_policy": "preflight_required",
        "unknown_action_policy": "block_until_act",
        "context_requirements": {},
    },
}

VALID_MODES = {"off", "advisory", "balanced", "strict"}
VALID_BASH_POLICIES = {"capture_only", "classify", "act_for_evidence", "act_for_all"}
VALID_EDIT_POLICIES = {"advisory", "act_required"}
VALID_FINAL_POLICIES = {"advisory", "preflight_required"}
VALID_UNKNOWN_POLICIES = {"allow_with_pressure", "block_until_act"}

READ_ONLY_BASH = re.compile(
    r"^\s*(?:"
    r"pwd|ls(?:\s|$)|find(?:\s|$)|rg(?:\s|$)|grep(?:\s|$)|"
    r"sed\s+-n(?:\s|$)|cat(?:\s|$)|head(?:\s|$)|tail(?:\s|$)|wc(?:\s|$)|nl(?:\s|$)|"
    r"git\s+(?:status|diff|log|show|branch)(?:\s|$)|"
    r"test\s+[-a-zA-Z](?:\s|$)"
    r")"
)
EVIDENCE_BASH = re.compile(
    r"(^|[\s;&|])(?:"
    r"pytest|tox|coverage|npm\s+test|pnpm\s+test|yarn\s+test|make\s+test|"
    r"python3?\s+-m\s+(?:pytest|unittest)|uv\s+run\s+pytest|cargo\s+test|go\s+test"
    r")(?:\s|$)"
)
MUTATION_BASH = re.compile(
    r"(^|[\s;&|])(?:"
    r"rm|mv|cp|mkdir|touch|chmod|chown|git\s+(?:add|commit|push|reset|checkout|merge|rebase)|"
    r"pip\s+install|python3?\s+-m\s+pip\s+install|npm\s+install|pnpm\s+install|yarn\s+add"
    r")(?:\s|$)|(?:>|>>)"
)


def merged_settings(*records: dict[str, Any] | None) -> dict[str, Any]:
    result = deepcopy(DEFAULT_SETTINGS)
    for record in records:
        if record:
            _deep_update(result, record)
    validate_settings(result)
    return result


def validate_settings(settings: dict[str, Any]) -> None:
    enforcement = settings.get("enforcement")
    if not isinstance(enforcement, dict):
        raise ValidationError("settings.enforcement must be an object")
    if enforcement.get("mode") not in VALID_MODES:
        raise ValidationError("unsupported_enforcement_mode")
    if enforcement.get("bash_policy") not in VALID_BASH_POLICIES:
        raise ValidationError("unsupported_bash_policy")
    if enforcement.get("edit_policy") not in VALID_EDIT_POLICIES:
        raise ValidationError("unsupported_edit_policy")
    if enforcement.get("final_policy") not in VALID_FINAL_POLICIES:
        raise ValidationError("unsupported_final_policy")
    if enforcement.get("unknown_action_policy") not in VALID_UNKNOWN_POLICIES:
        raise ValidationError("unsupported_unknown_action_policy")
    if not isinstance(enforcement.get("session_start_requires_frame"), bool):
        raise ValidationError("session_start_requires_frame must be boolean")
    context_requirements = enforcement.get("context_requirements", {})
    if not isinstance(context_requirements, dict):
        raise ValidationError("context_requirements must be an object")
    for kind, level in context_requirements.items():
        if kind not in CONTEXT_KINDS:
            raise ValidationError(f"unsupported_context_kind:{kind}")
        if level not in CONTEXT_REQUIREMENT_LEVELS:
            raise ValidationError(f"unsupported_context_requirement:{level}")


def context_requirements(settings: dict[str, Any]) -> dict[str, str]:
    enforcement = settings["enforcement"]
    mode = enforcement["mode"]
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
    return defaults


def required_context_kinds(settings: dict[str, Any]) -> list[str]:
    requirements = context_requirements(settings)
    return [kind for kind in CONTEXT_KINDS if requirements.get(kind) == "required"]


def classify_action(action_kind: str, action: dict[str, Any]) -> dict[str, Any]:
    if action_kind == "bash":
        command = str(action.get("command") or "").strip()
        if not command:
            label = "unknown"
        elif MUTATION_BASH.search(command):
            label = "mutation"
        elif EVIDENCE_BASH.search(command):
            label = "evidence_producing"
        elif READ_ONLY_BASH.search(command):
            label = "read_only_context"
        else:
            label = "unknown"
        return {"action_kind": action_kind, "classification": label, "command": command}
    if action_kind in {"edit", "file_edit", "mutation"}:
        return {"action_kind": action_kind, "classification": "mutation"}
    return {"action_kind": action_kind, "classification": "unknown"}


def action_pressure(settings: dict[str, Any], action_kind: str, action: dict[str, Any], *, open_act: str | None = None) -> dict[str, Any]:
    classification = classify_action(action_kind, action)
    enforcement = settings["enforcement"]
    mode = enforcement["mode"]
    required = _act_required(enforcement, action_kind, classification["classification"])
    blocked = required and open_act is None and mode in {"balanced", "strict"}
    level = "none"
    if blocked:
        level = "blocked"
    elif required:
        level = "high"
    elif mode == "advisory" and classification["classification"] in {"evidence_producing", "mutation", "unknown"}:
        level = "medium"
    return {
        "level": level,
        "mode": mode,
        "action_kind": action_kind,
        "classification": classification["classification"],
        "act_required": required,
        "open_act": open_act,
        "blocked": blocked,
        "why": _pressure_reason(enforcement, classification["classification"], required, blocked),
        "valid_moves": _pressure_moves(required, blocked),
    }


def _act_required(enforcement: dict[str, Any], action_kind: str, classification: str) -> bool:
    if enforcement["mode"] == "off":
        return False
    if action_kind == "bash":
        policy = enforcement["bash_policy"]
        if policy in {"capture_only", "classify"}:
            return False
        if policy == "act_for_all":
            return True
        if classification in {"evidence_producing", "mutation"}:
            return True
        return classification == "unknown" and enforcement["unknown_action_policy"] == "block_until_act"
    if action_kind in {"edit", "file_edit", "mutation"}:
        return enforcement["edit_policy"] == "act_required"
    return enforcement["unknown_action_policy"] == "block_until_act"


def _pressure_reason(enforcement: dict[str, Any], classification: str, required: bool, blocked: bool) -> str:
    if blocked:
        return "settings require an open ACT and protected_action_preflight before this action"
    if required:
        return "settings require this action to be bound to an open ACT"
    if enforcement["mode"] == "off":
        return "enforcement disabled"
    return f"action classified as {classification}; ACT not required by current settings"


def _pressure_moves(required: bool, blocked: bool) -> list[dict[str, Any]]:
    if required or blocked:
        return [
            move("probe_step", "open_probe", "Open an ACT for the action intent.", writes=True),
            move("probe_step", "protected_action_preflight", "Bind this action to the open ACT.", writes=True),
            move("brief", "brief_current_context", "Refresh current ledger and settings context."),
        ]
    return [
        move("run", "capture_bash_command", "Capture observed command output after execution.", writes=True),
        move("probe_step", "open_probe", "Open ACT if this command will be used as evidence.", writes=True),
    ]


def _deep_update(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = deepcopy(value)
