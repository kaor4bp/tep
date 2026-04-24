#!/usr/bin/env python3
"""Check whether the local Codex process can see the TEP plugin hooks."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


REQUIRED_HOOKS = {
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Stop",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_upward(start: Path, name: str) -> Path | None:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        path = candidate / name
        if path.exists():
            return path
    return None


def _check_http(url: str) -> dict[str, object]:
    endpoint = url.rstrip("/") + "/health"
    try:
        with urlopen(endpoint, timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return {"ok": bool(payload.get("ok")), "endpoint": endpoint, "payload": payload}
    except (OSError, URLError, json.JSONDecodeError) as exc:
        return {"ok": False, "endpoint": endpoint, "error": str(exc)}


def check(cwd: Path) -> dict[str, object]:
    repo = _repo_root()
    plugin_root = repo / "plugins" / "tep"
    manifest_path = plugin_root / ".codex-plugin" / "plugin.json"
    hooks_path = plugin_root / "hooks.json"
    skill_path = plugin_root / "skills" / "tep" / "SKILL.md"
    config_path = _codex_home() / "config.toml"
    pointer_path = _find_upward(cwd, ".tep")

    checks: list[dict[str, object]] = []

    def add(name: str, ok: bool, detail: str, *, repair: str | None = None) -> None:
        item: dict[str, object] = {"name": name, "ok": ok, "detail": detail}
        if repair:
            item["repair"] = repair
        checks.append(item)

    if manifest_path.exists():
        manifest = _read_json(manifest_path)
        add("plugin_manifest", manifest.get("name") == "tep", str(manifest_path))
        add("manifest_hooks_field", manifest.get("hooks") == "./hooks.json", str(manifest.get("hooks")))
        add("manifest_skills_field", manifest.get("skills") == "./skills/", str(manifest.get("skills")))
    else:
        manifest = {}
        add("plugin_manifest", False, str(manifest_path), repair="Restore plugins/tep/.codex-plugin/plugin.json.")

    if hooks_path.exists():
        hooks = _read_json(hooks_path).get("hooks", {})
        present = set(hooks) if isinstance(hooks, dict) else set()
        missing = sorted(REQUIRED_HOOKS - present)
        add("plugin_hooks_json", not missing, f"{hooks_path}; missing={missing}")
    else:
        add("plugin_hooks_json", False, str(hooks_path), repair="Restore plugins/tep/hooks.json.")

    add("plugin_skill", skill_path.exists(), str(skill_path))

    if config_path.exists():
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        features = config.get("features", {})
        plugins = config.get("plugins", {})
        marketplaces = config.get("marketplaces", {})
        tep_market = marketplaces.get("tep-local")
        tep_plugin = plugins.get("tep@tep-local")
        add("codex_hooks_feature", features.get("codex_hooks") is True, "features.codex_hooks")
        add("tep_marketplace", isinstance(tep_market, dict) and tep_market.get("source") == str(repo), str(tep_market))
        add("tep_plugin_enabled", isinstance(tep_plugin, dict) and tep_plugin.get("enabled") is True, str(tep_plugin))
    else:
        add("codex_config", False, str(config_path), repair="Create or repair ~/.codex/config.toml.")

    if pointer_path is None:
        add(
            "project_pointer",
            False,
            "No .tep found from cwd upward.",
            repair="Run: tep-init --project-root . --mcp-server http://127.0.0.1:8765",
        )
    else:
        pointer = _read_json(pointer_path)
        add("project_pointer", True, str(pointer_path))
        server = str(pointer.get("mcp_server", ""))
        if server.startswith("http://") or server.startswith("https://"):
            health = _check_http(server)
            add("http_transport_health", bool(health.get("ok")), json.dumps(health, sort_keys=True))
        else:
            add("http_transport_health", False, f"mcp_server={server!r}", repair="Use HTTP for standalone mode or start stdio explicitly.")

    ok = all(bool(item["ok"]) for item in checks if item["name"] not in {"project_pointer", "http_transport_health"})
    return {"ok": ok, "repo_root": str(repo), "checks": checks}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check-local-hooks.py")
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = check(Path(args.cwd))
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for item in result["checks"]:
            status = "ok" if item["ok"] else "missing"
            print(f"{status}: {item['name']} - {item['detail']}")
            if not item["ok"] and item.get("repair"):
                print(f"  repair: {item['repair']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
