"""Local storage migrations."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ids import LEGACY_ID_RE, PROTOCOL_ID_RE, shorten_legacy_id
from .jsoncanon import canonical_dumps, loads_no_duplicates


PROTECTED_JSONL_NAMES = {"ledger.jsonl", "source_events.jsonl"}


@dataclass(frozen=True)
class ShortIdMigrationResult:
    tep_home: str
    dry_run: bool
    id_map: dict[str, str] = field(default_factory=dict)
    protected_refs: list[str] = field(default_factory=list)
    rewritten_files: list[str] = field(default_factory=list)
    renamed_paths: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tep_home": self.tep_home,
            "dry_run": self.dry_run,
            "id_map": self.id_map,
            "protected_refs": self.protected_refs,
            "rewritten_files": self.rewritten_files,
            "renamed_paths": self.renamed_paths,
        }


def migrate_short_ids(tep_home: str | os.PathLike[str] = "~/.tep", *, dry_run: bool = False, random_chars: int = 16) -> ShortIdMigrationResult:
    """Shorten mutable legacy hex ids in a TEP home.

    Sealed append-only logs are not rewritten. Any legacy id mentioned by a
    ledger row or source event is left unchanged so existing replay still has
    the exact material it signed.
    """

    root = Path(tep_home).expanduser().resolve()
    protected_refs = _protected_refs(root)
    ids = sorted(_mutable_legacy_ids(root) - protected_refs)
    used = set(_all_protocol_ids(root))
    id_map = {old: shorten_legacy_id(old, random_chars=random_chars, used=used) for old in ids}
    rewritten_files: list[str] = []
    renamed_paths: list[dict[str, str]] = []

    if id_map:
        for path in _mutable_data_files(root):
            changed = _rewrite_file(path, id_map, dry_run=dry_run)
            if changed:
                rewritten_files.append(str(path))
        renamed_paths = _rename_paths(root, id_map, dry_run=dry_run)

    return ShortIdMigrationResult(
        tep_home=str(root),
        dry_run=dry_run,
        id_map=id_map,
        protected_refs=sorted(protected_refs),
        rewritten_files=rewritten_files,
        renamed_paths=renamed_paths,
    )


def _data_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file() and path.suffix in {".json", ".jsonl"})


def _mutable_data_files(root: Path) -> list[Path]:
    return [path for path in _data_files(root) if path.name not in PROTECTED_JSONL_NAMES]


def _protected_refs(root: Path) -> set[str]:
    refs: set[str] = set()
    for path in _data_files(root):
        if path.name not in PROTECTED_JSONL_NAMES:
            continue
        refs.update(match.group(0) for match in LEGACY_ID_RE.finditer(str(path)))
        text = path.read_text(encoding="utf-8")
        refs.update(match.group(0) for match in LEGACY_ID_RE.finditer(text))
    return refs


def _mutable_legacy_ids(root: Path) -> set[str]:
    ids: set[str] = set()
    for path in _mutable_data_files(root):
        ids.update(match.group(0) for match in LEGACY_ID_RE.finditer(path.read_text(encoding="utf-8")))
    return ids


def _all_protocol_ids(root: Path) -> set[str]:
    ids: set[str] = set()
    for path in _data_files(root):
        ids.update(match.group(0) for match in PROTOCOL_ID_RE.finditer(path.read_text(encoding="utf-8")))
    return ids


def _rewrite_file(path: Path, id_map: dict[str, str], *, dry_run: bool) -> bool:
    original = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        rows = [loads_no_duplicates(line) for line in original.splitlines() if line.strip()]
        rewritten = "".join(canonical_dumps(_replace_refs(row, id_map)) + "\n" for row in rows)
    else:
        rewritten = canonical_dumps(_replace_refs(json.loads(original), id_map)) + "\n"
    if rewritten == original:
        return False
    if not dry_run:
        path.write_text(rewritten, encoding="utf-8")
    return True


def _replace_refs(value: Any, id_map: dict[str, str]) -> Any:
    if isinstance(value, str):
        result = value
        for old, new in id_map.items():
            result = result.replace(old, new)
        return result
    if isinstance(value, list):
        return [_replace_refs(item, id_map) for item in value]
    if isinstance(value, dict):
        return {key: _replace_refs(child, id_map) for key, child in value.items()}
    return value


def _rename_paths(root: Path, id_map: dict[str, str], *, dry_run: bool) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if not any(old in path.name for old in id_map):
            continue
        new_name = path.name
        for old, new in id_map.items():
            new_name = new_name.replace(old, new)
        target = path.with_name(new_name)
        if target == path:
            continue
        changes.append({"from": str(path), "to": str(target)})
        if not dry_run:
            if target.exists():
                raise FileExistsError(f"migration target already exists: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            path.rename(target)
    return changes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tep-migrate-short-ids")
    parser.add_argument("--tep-home", default="~/.tep")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--random-chars", type=int, default=16)
    args = parser.parse_args(argv)
    result = migrate_short_ids(args.tep_home, dry_run=args.dry_run, random_chars=args.random_chars)
    print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
