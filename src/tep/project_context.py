"""Local project pointer helpers."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ValidationError
from .jsoncanon import canonical_dumps, read_json
from .storage import TEPHome
from .transactions import FileTransaction


@dataclass(frozen=True)
class ProjectPointer:
    tep_home: str
    project_ref: str
    mcp_server: str

    def as_dict(self) -> dict[str, str]:
        return {
            "tep_home": self.tep_home,
            "project_ref": self.project_ref,
            "mcp_server": self.mcp_server,
        }


def pointer_path(project_root: str | os.PathLike[str]) -> Path:
    return Path(project_root).expanduser().resolve() / ".tep"


def read_project_pointer(project_root: str | os.PathLike[str]) -> ProjectPointer:
    data = read_json(pointer_path(project_root))
    return ProjectPointer(
        tep_home=data["tep_home"],
        project_ref=data["project_ref"],
        mcp_server=data["mcp_server"],
    )


def write_project_pointer(
    project_root: str | os.PathLike[str],
    pointer: ProjectPointer,
    *,
    force: bool = False,
    tx: FileTransaction | None = None,
) -> ProjectPointer:
    path = pointer_path(project_root)
    if path.exists() and not force:
        raise ValidationError(f"project pointer already exists: {path}")
    content = canonical_dumps(pointer.as_dict()) + "\n"
    if tx is not None:
        tx.stage_text(path, content)
    else:
        path.write_text(content, encoding="utf-8")
    return pointer


def init_project_pointer(
    project_root: str | os.PathLike[str],
    *,
    tep_home: str | os.PathLike[str] = "~/.tep",
    project_ref: str | None = None,
    name: str | None = None,
    mcp_server: str = "stdio",
    force: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    store = TEPHome(tep_home)
    pointer_file = pointer_path(root)
    if pointer_file.exists() and not force:
        raise ValidationError(f"project pointer already exists: {pointer_file}")
    tx = store.begin_transaction("init_project_pointer")
    try:
        if project_ref is None:
            project = store.find_project_by_root(root)
            if project is None:
                project = store.register_project(name or root.name, roots=[str(root)], tx=tx)
            project_ref = project["id"]
        else:
            project = store.read_project(project_ref)
        pointer = write_project_pointer(
            root,
            ProjectPointer(str(Path(tep_home).expanduser()), project_ref, mcp_server),
            force=force,
            tx=tx,
        )
        store._commit_transaction(
            tx,
            "init_project_pointer",
            refs={"project_ref": project_ref, "project_root": str(root), "pointer_path": str(pointer_file)},
        )
    except Exception:
        tx.abort()
        raise
    return {
        "pointer": pointer.as_dict(),
        "project": project,
        "project_root": str(root),
        "pointer_path": str(pointer_path(root)),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tep-init")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--tep-home", default=os.environ.get("TEP_HOME", "~/.tep"))
    parser.add_argument("--project-ref")
    parser.add_argument("--name")
    parser.add_argument("--mcp-server", default=os.environ.get("TEP_MCP_SERVER", "stdio"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    result = init_project_pointer(
        args.project_root,
        tep_home=args.tep_home,
        project_ref=args.project_ref,
        name=args.name,
        mcp_server=args.mcp_server,
        force=args.force,
    )
    print(canonical_dumps(result))


if __name__ == "__main__":
    main()
