"""Shared filesystem formatting and hashing helpers."""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

LOGGER = logging.getLogger(__name__)


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


def atomic_write_many(
    writes: list[tuple[Path, Callable[[Path], None]]],
) -> list[Path]:
    """Write several files as a near-atomic group, with rollback on a caught error.

    Two phases. (1) STAGE: every file is written to a unique sibling temp via the
    caller's writer; if any writer raises here, no live target has changed, so the
    previous state stays fully intact. (2) SWAP: each staged temp is atomically moved
    onto its target; before overwriting an existing target its current bytes are
    copied aside, so if a swap RAISES the already-swapped targets are restored
    (best-effort -- a restore that itself fails is logged and swallowed, not
    re-raised, so the original error is preserved).

    This is NOT crash-proof. An OS-level kill DURING the forward swap loop bypasses
    rollback and can leave a partially-swapped set on disk. Order the writes so the
    most destructive / accumulating target (e.g. the option signal history) swaps
    LAST: the worst mid-swap kill then leaves the OLD accumulated state plus a mixed
    set of derived aliases (recoverable by re-running) -- never an advanced history
    with stale aliases. For true crash-atomicity use a single manifest/pointer swap
    instead of N independent target swaps. Within a single process this gives
    all-or-nothing under CAUGHT exceptions (a writer or guard raising), which is the
    common failure; pair it with a single-writer lock to exclude concurrent swaps.
    """

    # Phase 1 -- stage every file to a temp sibling. A writer failure here touches
    # no live target, so the previous published state is untouched.
    staged: list[tuple[Path, Path]] = []  # (tmp_path, final_path)
    try:
        for final_path, writer in writes:
            final_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = _unique_tmp_path(final_path)
            writer(tmp_path)
            staged.append((tmp_path, final_path))
    except BaseException:
        for tmp_path, _ in staged:
            _cleanup_tmp_path(tmp_path)
        raise

    # Phase 2 -- swap every staged temp onto its target, backing up the prior bytes
    # so a mid-swap failure rolls every already-swapped target back.
    swapped: list[tuple[Path, Path | None]] = []  # (final_path, backup_or_None)
    backups: list[Path] = []
    try:
        for tmp_path, final_path in staged:
            backup: Path | None = None
            if final_path.exists():
                backup = _unique_tmp_path(final_path)
                shutil.copy2(final_path, backup)
                backups.append(backup)
            _replace_with_retry(tmp_path, final_path)
            swapped.append((final_path, backup))
    except BaseException:
        for final_path, backup in reversed(swapped):
            try:
                if backup is not None:
                    _replace_with_retry(backup, final_path)
                else:
                    final_path.unlink(missing_ok=True)
            except OSError as restore_error:
                # Best-effort rollback: surface the failure (this target is now stale)
                # but keep restoring the rest and preserve the original exception.
                LOGGER.warning(
                    "atomic_write_many rollback could not restore %s: %s",
                    final_path,
                    restore_error,
                )
        for tmp_path, _ in staged:
            _cleanup_tmp_path(tmp_path)
        raise
    finally:
        for backup in backups:
            _cleanup_tmp_path(backup)
    return [final_path for _tmp_path, final_path in staged]


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
