"""Run metadata and audit helpers."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from golden_vector.app.paths import ProjectPaths


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def to_jsonable(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): to_jsonable(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and math.isnan(value):
        return None
    if value.__class__.__name__ in {"NAType", "NaTType"}:
        return None
    return value


@dataclass
class RunContext:
    """Holds the filesystem state for one pipeline run."""

    paths: ProjectPaths
    command: str
    parameters: dict[str, object]
    config_hash: str
    run_id: str
    run_dir: Path
    started_at_utc: str
    metadata_path: Path
    log_path: Path
    artifacts: list[str] = field(default_factory=list)

    @classmethod
    def start(
        cls,
        paths: ProjectPaths,
        command: str,
        parameters: dict[str, object],
        config_hash: str,
    ) -> "RunContext":
        paths.ensure_runtime_dirs()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"{timestamp}-{command}-{uuid4().hex[:8]}"
        run_dir = paths.ensure_run_dir(run_id)

        context = cls(
            paths=paths,
            command=command,
            parameters=parameters,
            config_hash=config_hash,
            run_id=run_id,
            run_dir=run_dir,
            started_at_utc=utc_now_iso(),
            metadata_path=run_dir / "metadata.json",
            log_path=run_dir / "run.log",
        )
        context._write_metadata(status="RUNNING", summary={}, notes=["Run created."])
        return context

    def write_json(self, file_name: str, payload: dict[str, Any]) -> Path:
        target = self.run_dir / file_name
        target.write_text(
            json.dumps(to_jsonable(payload), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        self.record_artifact(target)
        return target

    def record_artifact(self, path: Path) -> None:
        try:
            relative_path = path.relative_to(self.paths.repo_root)
            artifact_name = relative_path.as_posix()
        except ValueError:
            artifact_name = str(path)
        self.artifacts.append(artifact_name)

    def finalize(
        self,
        status: str,
        summary: dict[str, Any],
        notes: list[str] | None = None,
    ) -> None:
        self._write_metadata(status=status, summary=summary, notes=notes or [])

    def _write_metadata(
        self,
        status: str,
        summary: dict[str, Any],
        notes: list[str],
    ) -> None:
        payload = {
            "run_id": self.run_id,
            "command": self.command,
            "parameters": self.parameters,
            "config_hash": self.config_hash,
            "status": status,
            "started_at_utc": self.started_at_utc,
            "updated_at_utc": utc_now_iso(),
            "artifacts": sorted(set(self.artifacts)),
            "summary": summary,
            "notes": notes,
        }
        self.metadata_path.write_text(
            json.dumps(to_jsonable(payload), indent=2, sort_keys=True),
            encoding="utf-8",
        )
