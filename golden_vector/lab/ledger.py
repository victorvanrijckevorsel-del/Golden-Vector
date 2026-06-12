"""Variant ledger: every experiment config registered BEFORE compute.

Multiple-testing discipline from the Lab spec (F6): a backtest result is
admissible only if its exact configuration was sha256-registered in this
append-only ledger before the run. Deflated-Sharpe style corrections read
``n_trials`` from here — never from a human-supplied argument.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from golden_vector.common.files import atomic_write_text

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class VariantRecord:
    variant_hash: str
    signal_id: str
    registered_at_utc: str
    config: dict[str, Any]


def variant_hash(signal_id: str, config: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"signal_id": signal_id, "config": config},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def ledger_path(lab_dir: Path) -> Path:
    return lab_dir / "variant_ledger.jsonl"


def register_variant(
    *,
    lab_dir: Path,
    signal_id: str,
    config: dict[str, Any],
) -> VariantRecord:
    """Register a variant before compute; idempotent per exact config."""

    digest = variant_hash(signal_id, config)
    record = VariantRecord(
        variant_hash=digest,
        signal_id=signal_id,
        registered_at_utc=datetime.now(timezone.utc).isoformat(),
        config=config,
    )
    path = ledger_path(lab_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {entry.variant_hash for entry in load_ledger(lab_dir)}
    if digest not in existing:
        # If a crash tore the final line (no trailing newline), a plain
        # append would MERGE the new record onto it — the registration would
        # later be quarantined as unparseable and n_trials would silently
        # undercount. Always start on a fresh line.
        needs_newline = False
        if path.exists():
            tail = path.read_bytes()[-1:]
            needs_newline = bool(tail) and tail not in (b"\n", b"\r")
        with path.open("a", encoding="utf-8") as handle:
            if needs_newline:
                handle.write("\n")
            handle.write(
                json.dumps(
                    {
                        "variant_hash": record.variant_hash,
                        "signal_id": record.signal_id,
                        "registered_at_utc": record.registered_at_utc,
                        "config": record.config,
                    },
                    sort_keys=True,
                    default=str,
                )
                + "\n"
            )
    return record


def load_ledger(lab_dir: Path) -> list[VariantRecord]:
    path = ledger_path(lab_dir)
    if not path.exists():
        return []
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    lines = [line for line in lines if line]
    records: list[VariantRecord] = []
    for index, line in enumerate(lines):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            # A crash mid-append can tear only the FINAL line; quarantine it
            # so registration/gating keep working. A malformed line anywhere
            # else means real corruption — fail loud.
            if index == len(lines) - 1:
                quarantine = path.with_suffix(".jsonl.torn")
                quarantine.write_text(line + "\n", encoding="utf-8")
                # Rewrite the ledger without the torn line so it cannot
                # swallow a future append.
                atomic_write_text(path, "".join(l + "\n" for l in lines[:-1]))
                LOGGER.warning(
                    "Variant ledger: torn final line quarantined to %s and "
                    "removed from the ledger.",
                    quarantine,
                )
                break
            raise
        records.append(
            VariantRecord(
                variant_hash=str(payload["variant_hash"]),
                signal_id=str(payload["signal_id"]),
                registered_at_utc=str(payload["registered_at_utc"]),
                config=dict(payload["config"]),
            )
        )
    return records


def n_trials(lab_dir: Path, *, signal_id: str | None = None) -> int:
    """Trial count for multiple-testing corrections — ledger is the truth."""

    records = load_ledger(lab_dir)
    if signal_id is None:
        return len(records)
    return sum(1 for record in records if record.signal_id == signal_id)


def require_registered(
    *,
    lab_dir: Path,
    signal_id: str,
    config: dict[str, Any],
) -> str:
    """Admissibility gate: raise unless this exact variant was registered."""

    digest = variant_hash(signal_id, config)
    if digest not in {entry.variant_hash for entry in load_ledger(lab_dir)}:
        raise ValueError(
            f"Variant {digest[:12]} for signal '{signal_id}' is not in the "
            "ledger; register_variant() must run BEFORE compute."
        )
    return digest
