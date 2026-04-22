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


@dataclass(frozen=True)
class LoadedConfig:
    """Validated app config plus file hashes."""

    app: AppConfig
    file_hashes: dict[str, str]
    combined_hash: str


def load_app_config(paths: ProjectPaths) -> LoadedConfig:
    raw_configs: dict[str, Any] = {}
    file_hashes: dict[str, str] = {}

    expected_files = {
        "universe": paths.config_path("universe.yaml"),
        "horizons": paths.config_path("horizons.yaml"),
        "qa": paths.config_path("qa.yaml"),
        "scoring": paths.config_path("scoring.yaml"),
        "screening_params": paths.config_path("screening_params.yaml"),
    }

    for config_name, config_path in expected_files.items():
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
