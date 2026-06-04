"""Config loading and validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.config_models import AppConfig

EXPECTED_CONFIG_FILES: tuple[tuple[str, str], ...] = (
    ("universe", "universe.yaml"),
    ("benchmarks", "benchmarks.yaml"),
    ("candidate_finder", "candidate_finder.yaml"),
    ("hedge_readiness", "hedge_readiness.yaml"),
    ("tool_c", "tool_c.yaml"),
    ("tool_d", "tool_d.yaml"),
    ("horizons", "horizons.yaml"),
    ("qa", "qa.yaml"),
    ("scoring", "scoring.yaml"),
    ("screening_params", "screening_params.yaml"),
)


@dataclass(frozen=True)
class LoadedConfig:
    """Validated app config plus file hashes."""

    app: AppConfig
    file_hashes: dict[str, str]
    combined_hash: str


def expected_config_paths(paths: ProjectPaths) -> dict[str, Path]:
    return {
        config_name: paths.config_path(file_name)
        for config_name, file_name in EXPECTED_CONFIG_FILES
    }


def load_app_config(paths: ProjectPaths) -> LoadedConfig:
    raw_configs: dict[str, Any] = {}
    file_hashes: dict[str, str] = {}

    for config_name, config_path in expected_config_paths(paths).items():
        raw_bytes = _read_required_bytes(config_path)
        raw_configs[config_name] = yaml.safe_load(raw_bytes.decode("utf-8")) or {}
        file_hashes[config_name] = hashlib.sha256(raw_bytes).hexdigest()

    app_config = AppConfig.model_validate(raw_configs)
    combined_hash = hashlib.sha256(
        json.dumps(file_hashes, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return LoadedConfig(app=app_config, file_hashes=file_hashes, combined_hash=combined_hash)


def _read_required_bytes(path: Path) -> bytes:
    if not path.exists():
        raise FileNotFoundError(f"Required config file is missing: {path}")
    return path.read_bytes()
