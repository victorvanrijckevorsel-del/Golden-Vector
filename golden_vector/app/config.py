"""Config loading and validation."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.config_models import AppConfig

EXPECTED_CONFIG_FILES: tuple[tuple[str, str], ...] = (
    ("universe", "universe.yaml"),
    ("benchmarks", "benchmarks.yaml"),
    ("market_data", "market_data.yaml"),
    ("candidate_finder", "candidate_finder.yaml"),
    ("hedge_readiness", "hedge_readiness.yaml"),
    ("tool_c", "tool_c.yaml"),
    ("tool_d", "tool_d.yaml"),
    ("horizons", "horizons.yaml"),
    ("qa", "qa.yaml"),
    ("scoring", "scoring.yaml"),
    ("screening_params", "screening_params.yaml"),
)

OPTIONAL_CONFIG_FILES: tuple[tuple[str, str], ...] = (
    ("portfolio", "portfolio.yaml"),
)
LOCAL_CONFIG_FILES: tuple[tuple[str, str], ...] = (
    ("portfolio", "portfolio.local.yaml"),
)
PORTFOLIO_ENABLED_ENV = "GV_PORTFOLIO_ENABLED"


@dataclass(frozen=True)
class LoadedConfig:
    """Validated app config plus file hashes."""

    app: AppConfig
    file_hashes: dict[str, str]
    config_hash: str


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

    for config_name, file_name in OPTIONAL_CONFIG_FILES:
        config_path = paths.config_path(file_name)
        if not config_path.exists():
            continue
        raw_bytes = config_path.read_bytes()
        raw_configs[config_name] = yaml.safe_load(raw_bytes.decode("utf-8")) or {}
        file_hashes[config_name] = hashlib.sha256(raw_bytes).hexdigest()

    for config_name, file_name in LOCAL_CONFIG_FILES:
        config_path = paths.config_path(file_name)
        if not config_path.exists():
            continue
        raw_bytes = config_path.read_bytes()
        local_config = yaml.safe_load(raw_bytes.decode("utf-8")) or {}
        _merge_config_section(raw_configs, config_name, local_config)
        file_hashes[f"{config_name}_local"] = hashlib.sha256(raw_bytes).hexdigest()

    portfolio_enabled_override = os.environ.get(PORTFOLIO_ENABLED_ENV)
    if portfolio_enabled_override is not None:
        _merge_config_section(
            raw_configs,
            "portfolio",
            {
                "enabled": _parse_bool_env(
                    PORTFOLIO_ENABLED_ENV,
                    portfolio_enabled_override,
                )
            },
        )
        file_hashes["portfolio_env_override"] = hashlib.sha256(
            portfolio_enabled_override.encode("utf-8")
        ).hexdigest()

    app_config = AppConfig.model_validate(raw_configs)
    config_hash = hashlib.sha256(
        json.dumps(file_hashes, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return LoadedConfig(app=app_config, file_hashes=file_hashes, config_hash=config_hash)


def _read_required_bytes(path: Path) -> bytes:
    if not path.exists():
        raise FileNotFoundError(f"Required config file is missing: {path}")
    return path.read_bytes()


def _merge_config_section(
    raw_configs: dict[str, Any],
    config_name: str,
    override: Any,
) -> None:
    base = raw_configs.get(config_name) or {}
    if isinstance(base, dict) and isinstance(override, dict):
        raw_configs[config_name] = {**base, **override}
        return
    raw_configs[config_name] = override


def _parse_bool_env(name: str, raw_value: str) -> bool:
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be one of true/false, yes/no, on/off, or 1/0")
