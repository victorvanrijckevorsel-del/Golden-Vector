"""Shared filesystem formatting and hashing helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4


def repo_relative(paths: Any, path: Path) -> str:
    """Return a repo-relative path when possible, otherwise an absolute string."""

    try:
        return path.relative_to(paths.repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def sha256_file(path: Path) -> str:
    """Return the SHA256 hex digest for a file, raising on read errors."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def optional_sha256_file(path: Path | None) -> str | None:
    """Best-effort SHA256 helper for cache keys and optional provenance."""

    if path is None or not path.exists():
        return None
    try:
        return sha256_file(path)
    except OSError:
        return None


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> Path:
    """Write text via a unique sibling temp file and atomic replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _unique_tmp_path(path)
    try:
        tmp_path.write_text(text, encoding=encoding)
        tmp_path.replace(path)
    finally:
        _cleanup_tmp_path(tmp_path)
    return path


def atomic_write_bytes(path: Path, data: bytes) -> Path:
    """Write bytes via a unique sibling temp file and atomic replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _unique_tmp_path(path)
    try:
        tmp_path.write_bytes(data)
        tmp_path.replace(path)
    finally:
        _cleanup_tmp_path(tmp_path)
    return path


def _unique_tmp_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.{uuid4().hex}.tmp")


def _cleanup_tmp_path(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass
