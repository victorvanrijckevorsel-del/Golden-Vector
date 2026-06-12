"""Shared filesystem formatting and hashing helpers."""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
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


def safe_file_fragment(value: object) -> str:
    """Return a filesystem-safe fragment for run ids and snapshot stamps."""

    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("._") or "unknown"


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> Path:
    """Write text via a unique sibling temp file and atomic replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _unique_tmp_path(path)
    try:
        tmp_path.write_text(text, encoding=encoding)
        _replace_with_retry(tmp_path, path)
    finally:
        _cleanup_tmp_path(tmp_path)
    return path


def atomic_write_bytes(path: Path, data: bytes) -> Path:
    """Write bytes via a unique sibling temp file and atomic replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _unique_tmp_path(path)
    try:
        tmp_path.write_bytes(data)
        _replace_with_retry(tmp_path, path)
    finally:
        _cleanup_tmp_path(tmp_path)
    return path


def atomic_write_file(path: Path, writer: Callable[[Path], None]) -> Path:
    """Write a file with a caller-supplied writer, then atomically replace target."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _unique_tmp_path(path)
    try:
        writer(tmp_path)
        _replace_with_retry(tmp_path, path)
    finally:
        _cleanup_tmp_path(tmp_path)
    return path


def _replace_with_retry(tmp_path: Path, path: Path) -> None:
    """Atomic replace with a bounded retry on Windows sharing violations.

    On Windows, os.replace raises PermissionError (WinError 5) while ANY
    process holds the destination open - and the workspace server reads
    latest aliases and the model-state manifest on every request, so every
    publish can collide with a read. Retry briefly on PermissionError only;
    everything else stays fail-loud.
    """

    delay = 0.01
    for _ in range(8):
        try:
            tmp_path.replace(path)
            return
        except PermissionError:
            time.sleep(delay)
            delay = min(delay * 2, 0.5)
    tmp_path.replace(path)


def _unique_tmp_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.{uuid4().hex}.tmp")


def _cleanup_tmp_path(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass
