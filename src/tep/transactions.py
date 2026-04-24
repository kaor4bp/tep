"""Best-effort multi-file transactions for local TEP storage."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import StorageError
from .ids import new_id
from .jsoncanon import bytes_hash, canonical_dumps


@dataclass(frozen=True)
class StagedWrite:
    final_path: Path
    staged_path: Path
    content_hash: str
    existed_before: bool


@dataclass
class FileTransaction:
    """Stage files under runtime/tx and commit them as one logical mutation.

    This is not a database transaction. It preflights every destination before
    writing, then rolls back already-replaced files if a later replace fails.
    """

    root: Path
    operation: str
    tx_ref: str = field(default_factory=lambda: new_id("TX"))

    def __post_init__(self) -> None:
        self.root = self.root.expanduser()
        self.tx_dir = self.root / "runtime" / "tx" / self.tx_ref
        self.staged_dir = self.tx_dir / "staged"
        self.backup_dir = self.tx_dir / "backup"
        self._writes: list[StagedWrite] = []
        self._committed = False
        self.tx_dir.mkdir(parents=True, exist_ok=False)
        self.staged_dir.mkdir(parents=True, exist_ok=True)
        self._write_text(self.tx_dir / "intent.json", canonical_dumps({"tx_ref": self.tx_ref, "operation": self.operation}) + "\n")

    @property
    def writes(self) -> tuple[StagedWrite, ...]:
        return tuple(self._writes)

    def stage_json(self, final_path: Path, record: dict[str, Any]) -> None:
        self.stage_text(final_path, canonical_dumps(record) + "\n")

    def stage_text(self, final_path: Path, content: str) -> None:
        final = final_path.expanduser()
        if any(item.final_path == final for item in self._writes):
            raise StorageError(f"duplicate staged path in transaction: {final}")
        staged = self.staged_dir / f"{len(self._writes):04d}.blob"
        self._write_text(staged, content)
        self._writes.append(
            StagedWrite(
                final_path=final,
                staged_path=staged,
                content_hash=bytes_hash(content.encode("utf-8")),
                existed_before=final.exists(),
            )
        )

    def commit(self) -> dict[str, Any]:
        self._preflight()
        replaced: list[StagedWrite] = []
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        try:
            for item in self._writes:
                item.final_path.parent.mkdir(parents=True, exist_ok=True)
                backup = self._backup_path(item)
                if item.final_path.exists():
                    shutil.copy2(item.final_path, backup)
                os.replace(item.staged_path, item.final_path)
                replaced.append(item)
        except Exception as exc:  # pragma: no cover - hard to trigger portably
            self._rollback(replaced)
            raise StorageError(f"transaction commit failed and was rolled back: {self.tx_ref}") from exc

        self._committed = True
        commit = {
            "tx_ref": self.tx_ref,
            "operation": self.operation,
            "writes": [
                {
                    "path": str(item.final_path),
                    "content_hash": item.content_hash,
                    "existed_before": item.existed_before,
                }
                for item in self._writes
            ],
        }
        self._write_text(self.tx_dir / "commit.json", canonical_dumps(commit) + "\n")
        return commit

    def abort(self) -> None:
        if not self._committed and self.tx_dir.exists():
            shutil.rmtree(self.tx_dir)

    def _preflight(self) -> None:
        for item in self._writes:
            if item.final_path.exists() and not item.final_path.is_file():
                raise StorageError(f"transaction destination is not a file: {item.final_path}")
            if not item.staged_path.is_file():
                raise StorageError(f"transaction staged blob is missing: {item.staged_path}")

    def _rollback(self, replaced: list[StagedWrite]) -> None:
        for item in reversed(replaced):
            backup = self._backup_path(item)
            if item.existed_before:
                os.replace(backup, item.final_path)
            elif item.final_path.exists():
                item.final_path.unlink()

    def _backup_path(self, item: StagedWrite) -> Path:
        return self.backup_dir / f"{self._writes.index(item):04d}.bak"

    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

