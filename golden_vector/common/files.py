"""Shared filesystem formatting and hashing helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


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
