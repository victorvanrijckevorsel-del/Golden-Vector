"""Data loading and screen execution for the Candidate Finder."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import yaml

from golden_vector.common.files import optional_sha256_file as _file_sha256
from golden_vector.common.numeric import require_finite_positive
from golden_vector.common.strings import unique_strings as _common_unique_strings
from golden_vector.app.latest_data import load_latest_foundation_snapshot
from golden_vector.app.model_state import (
    load_current_model_state_manifest,
    read_current_model_parquet,
    resolve_current_foundation_manifest_path,
    resolve_current_model_artifact_path,
    summarize_model_state_alignment,
)
from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.config_models import (
    AppConfig,
    CandidateFinderConfig,
    CandidateFinderPreset,
    CandidateFinderPresetCriterion,
)
from golden_vector.model.candidate_finder import (
    CandidateFinderResult,
    CriterionSelection,
    rank_candidates,
)
from golden_vector.model.tool_d import (
    ToolDExecutionInputs,
    compute_tool_d_outputs,
    latest_gold_price_from_history,
)
from golden_vector.fundamentals.artifacts import load_official_fundamentals
from golden_vector.contracts.fundamentals import fetched_fundamentals_latest_path
from golden_vector.screening.manual_data import load_manual_screening_data
from golden_vector.screening.schema import validate_tool_b_output_schema
from golden_vector.screening.manual_store import load_store_tables
from golden_vector.screening.pipeline import compute_tool_b_in_memory
from golden_vector.hedge.option_availability import has_usable_option_slots
from golden_vector.serve.format_helpers import _first_frame_number
from golden_vector.serve.option_trading_data import (
    OptionTradingData,
    load_option_trading_data,
)

OptionsSide = Literal["puts", "calls", "either", "none"]
TOOL_D_FINDER_FIELDS = frozenset(
    {
        "tool_d_quality_rank",
        "interest_cover_gold_usd",
        "debt_stress_gold_usd",
        "fcf_breakeven_gold_usd",
        "cost_curve_aisc_percentile",
    }
)
TOOL_B_GOLD_SCENARIO_FIELDS = frozenset(
    {
        "ev_ebitda",
        "forward_pe",
        "fcf_yield",
        "margin_pct",
    }
)
_SCENARIO_SOURCE_RUN_ID = "candidate-finder-scenario"
_CACHE_MAX_SIZE = 32


class CandidateFinderScenarioError(ValueError):
    """Raised when a Candidate Finder scenario request is invalid."""


class CandidateFinderSourceError(RuntimeError):
    """Raised when a resolved current Candidate Finder source artifact is corrupt or
    unreadable. Fail loud rather than rendering a sparse ranking that silently drops
    whole dimensions (audit M7)."""


@dataclass(frozen=True)
class CandidateFinderCacheKey:
    tool_a_refresh_run_ids: tuple[str, ...]
    tool_b_refresh_run_ids: tuple[str, ...]
    tool_c_refresh_run_ids: tuple[str, ...]
    tool_d_refresh_run_ids: tuple[str, ...]
    options_refresh_run_id: str
    manual_store_hash: str | None
    tool_a_latest_hash: str | None
    tool_b_latest_hash: str | None
    tool_c_latest_hash: str | None
    tool_d_latest_hash: str | None
    model_state_manifest_hash: str | None = None
    scenario_gold_price: float | None = None
    scenario_foundation_manifest_hash: str | None = None
    scenario_fundamentals_hash: str | None = None


@dataclass(frozen=True)
class CandidateFinderSourceLoad:
    frame: pd.DataFrame
    warning: str | None = None


@dataclass(frozen=True)
class CandidateFinderScenario:
    gold_price: float

    @classmethod
    def from_value(cls, value: object) -> "CandidateFinderScenario":
        return cls(gold_price=require_finite_positive("gold_price", value))


@dataclass(frozen=True)
class _CandidateFinderScenarioSources:
    tool_b: CandidateFinderSourceLoad
    tool_d: CandidateFinderSourceLoad
    gold_price_used: float
    spot_gold_usd: float
    spot_gold_date: str | None
    source_basis: str
    rank_basis: str


@dataclass(frozen=True)
class CandidateFinderAlignment:
    status: Literal["OK", "WARN", "UNKNOWN"]
    message: str | None
    tool_a_refresh_run_ids: tuple[str, ...]
    tool_b_refresh_run_ids: tuple[str, ...]
    tool_c_refresh_run_ids: tuple[str, ...]
    tool_d_refresh_run_ids: tuple[str, ...]
    options_refresh_run_id: str | None
    manual_store_hash: str | None
    manual_store_as_of: str | None
    messages: tuple[str, ...]


@dataclass(frozen=True)
class CandidateFinderData:
    frame: pd.DataFrame
    criteria_config: CandidateFinderConfig
    alignment: CandidateFinderAlignment
    cache_key: CandidateFinderCacheKey
    model_state_manifest: dict[str, Any] | None = None
    gold_price_used: float | None = None
    spot_gold_usd: float | None = None
    spot_gold_date: str | None = None
    source_basis: str = "persisted_spot"
    rank_basis: str = "persisted_current"
    scenario_requested_gold_price: float | None = None
    scenario_active: bool = False
    scenario_error: str | None = None


@dataclass(frozen=True)
class CandidateFinderScreen:
    data: CandidateFinderData
    ranking: CandidateFinderResult
    peer_frame: pd.DataFrame
    options_side: OptionsSide
    top_n: int
    warnings: tuple[str, ...]


_CACHE: OrderedDict[CandidateFinderCacheKey, CandidateFinderData] = OrderedDict()


def clear_candidate_finder_cache() -> None:
    _CACHE.clear()


def parse_candidate_finder_scenario(
    query: Mapping[str, Sequence[str]],
) -> CandidateFinderScenario | None:
    """Parse the optional Candidate Finder gold-price scenario from a query."""

    raw_values = query.get("gold_price")
    if not raw_values:
        return None
    raw_value = str(raw_values[0]).strip()
    if not raw_value:
        return None
    try:
        return CandidateFinderScenario.from_value(raw_value)
    except ValueError as exc:
        raise CandidateFinderScenarioError(str(exc)) from exc


def load_candidate_finder_data(
    paths: ProjectPaths,
    *,
    app_config: AppConfig,
    scenario: CandidateFinderScenario | None = None,
) -> CandidateFinderData:
    """Load the latest joined frame used by Candidate Finder screens."""

    model_state_manifest = load_current_model_state_manifest(paths)
    tool_a_path, tool_a_required = _resolve_finder_source(
        paths, "tool_a", fallback_path=paths.latest_tool_a_snapshot_parquet_path
    )
    tool_b_path, tool_b_required = _resolve_finder_source(
        paths, "tool_b", fallback_path=paths.latest_tool_b_snapshot_parquet_path
    )
    tool_c_path, tool_c_required = _resolve_finder_source(
        paths, "tool_c", fallback_path=paths.latest_tool_c_snapshot_parquet_path
    )
    tool_d_source_path, tool_d_required = _tool_d_finder_source(paths)
    tool_a_load = _read_optional_parquet(
        tool_a_path, label="Gold Sensitivity", required=tool_a_required
    )
    tool_b_load = _read_optional_parquet(
        tool_b_path, label="Corporate Finance", required=tool_b_required
    )
    tool_a = tool_a_load.frame
    tool_b = tool_b_load.frame
    tool_c_load = _read_optional_parquet(
        tool_c_path, label="Gold Downside", required=tool_c_required
    )
    tool_d_load = _read_optional_parquet(
        tool_d_source_path, label="Corporate Resilience", required=tool_d_required
    )
    tool_c = tool_c_load.frame
    option_data = load_option_trading_data(paths, app_config=app_config)
    manual_company, _, _, _ = load_store_tables(paths)
    manual_hash = _file_sha256(paths.manual_screening_store_path)
    manual_as_of = _manual_as_of(manual_company)
    options_refresh_run_id = _options_refresh_run_id(option_data)
    scenario_foundation_manifest_path: Path | None = None
    scenario_foundation_error: Exception | None = None
    if scenario is not None:
        try:
            scenario_foundation_manifest_path = resolve_current_foundation_manifest_path(
                paths,
                require_current_manifest=True,
            )
        except Exception as exc:
            scenario_foundation_error = exc
    cache_key = CandidateFinderCacheKey(
        tool_a_refresh_run_ids=_unique_strings(tool_a, "snapshot_refresh_run_id"),
        tool_b_refresh_run_ids=_unique_strings(tool_b, "snapshot_refresh_run_id"),
        tool_c_refresh_run_ids=_unique_strings(tool_c, "snapshot_refresh_run_id"),
        tool_d_refresh_run_ids=_unique_strings(tool_d_load.frame, "snapshot_refresh_run_id"),
        options_refresh_run_id=options_refresh_run_id or "unknown",
        manual_store_hash=manual_hash,
        tool_a_latest_hash=_file_sha256(tool_a_path),
        tool_b_latest_hash=_file_sha256(tool_b_path),
        tool_c_latest_hash=_file_sha256(tool_c_path),
        tool_d_latest_hash=_file_sha256(tool_d_source_path),
        model_state_manifest_hash=_file_sha256(paths.latest_model_state_manifest_path),
        scenario_gold_price=_cache_gold_price(scenario),
        scenario_foundation_manifest_hash=_file_sha256(scenario_foundation_manifest_path),
        scenario_fundamentals_hash=(
            _file_sha256(fetched_fundamentals_latest_path(paths))
            if scenario is not None
            else None
        ),
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    scenario_error: str | None = None
    scenario_requested_gold_price = scenario.gold_price if scenario is not None else None
    if scenario is not None:
        try:
            if scenario_foundation_error is not None:
                raise scenario_foundation_error
            scenario_sources = _compute_scenario_sources(
                paths=paths,
                app_config=app_config,
                scenario=scenario,
                foundation_manifest_path=scenario_foundation_manifest_path,
            )
            tool_b_load = scenario_sources.tool_b
            tool_b = tool_b_load.frame
            tool_d_load = scenario_sources.tool_d
            tool_d = tool_d_load.frame
            scenario_active = True
            gold_price_used = scenario_sources.gold_price_used
            spot_gold_usd = scenario_sources.spot_gold_usd
            spot_gold_date = scenario_sources.spot_gold_date
            source_basis = scenario_sources.source_basis
            rank_basis = scenario_sources.rank_basis
        except Exception as exc:
            scenario_error = f"Could not compute Candidate Finder scenario: {exc}"
            tool_b_spot_load = _spot_tool_b_source(tool_b_load.frame)
            tool_d_spot_load = _spot_tool_d_source(tool_d_load.frame)
            tool_b_load = tool_b_spot_load
            tool_b = tool_b_load.frame
            tool_d_load = tool_d_spot_load
            tool_d = tool_d_load.frame
            scenario_active = False
            gold_price_used = _first_provenance_number("gold_price_used", tool_b, tool_d)
            spot_gold_usd = _first_provenance_number("spot_gold_usd", tool_b, tool_d)
            spot_gold_date = _first_provenance_text("spot_gold_date", tool_b, tool_d)
            source_basis = "persisted_spot"
            rank_basis = "persisted_current"
    else:
        tool_b_spot_load = _spot_tool_b_source(tool_b_load.frame)
        tool_d_spot_load = _spot_tool_d_source(tool_d_load.frame)
        tool_b_load = tool_b_spot_load
        tool_b = tool_b_load.frame
        tool_d_load = tool_d_spot_load
        tool_d = tool_d_load.frame
        scenario_active = False
        gold_price_used = _first_provenance_number("gold_price_used", tool_b, tool_d)
        spot_gold_usd = _first_provenance_number("spot_gold_usd", tool_b, tool_d)
        spot_gold_date = _first_provenance_text("spot_gold_date", tool_b, tool_d)
        source_basis = "persisted_spot"
        rank_basis = "persisted_current"

    frame = _joined_frame(
        app_config=app_config,
        tool_a=tool_a,
        tool_b=tool_b,
        tool_c=tool_c,
        tool_d=tool_d,
        options=option_data.options_features,
        manual_company=manual_company,
        option_data=option_data,
    )
    alignment = _alignment(
        model_state_manifest=model_state_manifest,
        tool_a=tool_a,
        tool_b=tool_b,
        tool_c=tool_c,
        tool_d=tool_d,
        options_refresh_run_id=options_refresh_run_id,
        manual_store_hash=manual_hash,
        manual_store_as_of=manual_as_of,
        source_load_warnings=tuple(
            [
                warning
                for warning in (
                    tool_a_load.warning,
                    tool_b_load.warning,
                    tool_c_load.warning,
                    tool_d_load.warning,
                    scenario_error,
                )
                if warning is not None
            ]
            + list(_joined_frame_warnings(frame))
        ),
        scenario_active=scenario_active,
    )
    data = CandidateFinderData(
        frame=frame,
        criteria_config=app_config.candidate_finder,
        alignment=alignment,
        cache_key=cache_key,
        model_state_manifest=model_state_manifest,
        gold_price_used=gold_price_used,
        spot_gold_usd=spot_gold_usd,
        spot_gold_date=spot_gold_date,
        source_basis=source_basis,
        rank_basis=rank_basis,
        scenario_requested_gold_price=scenario_requested_gold_price,
        scenario_active=scenario_active,
        scenario_error=scenario_error,
    )
    if scenario_error is None:
        _cache_set(cache_key, data)
    return data


def load_candidate_finder_spec(path: Path) -> dict[str, Any]:
    """Load a JSON/YAML Candidate Finder screen spec."""

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("candidate finder spec must be a mapping")
    return dict(raw)


def run_candidate_finder_screen(
    data: CandidateFinderData,
    *,
    spec: Mapping[str, Any] | None = None,
) -> CandidateFinderScreen:
    """Apply a screen spec and return ranked Candidate Finder results."""

    screen_spec = dict(spec or {})
    spec_warnings: list[str] = []
    preset = _preset(screen_spec, data.criteria_config)
    if _preset_id(screen_spec) and preset is None:
        spec_warnings.append(f"Unknown preset ignored: {_preset_id(screen_spec)}.")
    options_side = _options_side(
        screen_spec,
        preset=preset,
        warnings=spec_warnings,
    )
    peer_frame = _apply_options_filter(data.frame, options_side=options_side)
    top_n = _top_n(screen_spec, data.criteria_config, warnings=spec_warnings)
    selections = _selections(
        screen_spec,
        preset=preset,
        warnings=spec_warnings,
    )
    ranking = rank_candidates(
        peer_frame,
        criteria=list(data.criteria_config.criteria),
        selections=selections,
        top_n=top_n,
        min_criteria_fraction=data.criteria_config.min_criteria_fraction,
    )
    warnings = list(data.alignment.messages) + spec_warnings + list(ranking.warnings)
    if data.alignment.status != "OK":
        fallback = "Candidate Finder sources are not aligned."
        if data.alignment.message and data.alignment.message not in warnings:
            warnings.insert(0, data.alignment.message or fallback)
    if peer_frame.empty:
        warnings.append("No tickers survived the options-side filter.")
    return CandidateFinderScreen(
        data=data,
        ranking=ranking,
        peer_frame=peer_frame,
        options_side=options_side,
        top_n=top_n,
        warnings=tuple(warnings),
    )


def candidate_finder_result_frame(screen: CandidateFinderScreen) -> pd.DataFrame:
    """Flatten ranked rows for CLI parquet output."""

    rows: list[dict[str, Any]] = []
    for row in screen.ranking.rows:
        output: dict[str, Any] = {
            "ticker": row.ticker,
            "rank": row.rank,
            "score": row.score,
            "rank_eligible": row.rank_eligible,
            "present_criteria_count": row.present_criteria_count,
            "selected_criteria_count": row.selected_criteria_count,
            "criteria_fraction": row.criteria_fraction,
            "top_n_tally": row.top_n_tally,
            "source_score_eligible": row.source_score_eligible,
            "options_side": screen.options_side,
            "alignment_status": screen.data.alignment.status,
            "alignment_message": screen.data.alignment.message,
            "gold_price_used": screen.data.gold_price_used,
            "spot_gold_usd": screen.data.spot_gold_usd,
            "spot_gold_date": screen.data.spot_gold_date,
            "source_basis": screen.data.source_basis,
            "rank_basis": screen.data.rank_basis,
            "scenario_active": screen.data.scenario_active,
        }
        for criterion in screen.ranking.selected_criteria:
            output[f"raw_{criterion.id}"] = row.raw_values.get(criterion.id)
            output[f"percentile_{criterion.id}"] = row.percentiles.get(criterion.id)
        rows.append(output)
    return pd.DataFrame(rows)


def _joined_frame(
    *,
    app_config: AppConfig,
    tool_a: pd.DataFrame,
    tool_b: pd.DataFrame,
    tool_c: pd.DataFrame,
    tool_d: pd.DataFrame,
    options: pd.DataFrame,
    manual_company: pd.DataFrame,
    option_data: OptionTradingData,
) -> pd.DataFrame:
    base = pd.DataFrame(
        {
            "ticker": sorted(
                {
                    ticker.ticker
                    for ticker in app_config.universe.tickers
                    if ticker.active
                }
            )
        }
    )
    joined = base
    joined = _merge_source(
        joined,
        _prepare_source(tool_a, rename=_TOOL_A_RENAMES),
    )
    joined = _merge_source(
        joined,
        _prepare_source(tool_b, rename=_TOOL_B_RENAMES),
    )
    joined = _merge_source(
        joined,
        _prepare_source(tool_c, rename=_TOOL_C_RENAMES),
    )
    joined = _merge_source(
        joined,
        _prepare_source(tool_d, rename=_TOOL_D_RENAMES),
    )
    joined = _merge_source(
        joined,
        _prepare_source(manual_company, rename=_MANUAL_RENAMES),
    )
    joined = _merge_source(
        joined,
        _prepare_source(options, rename=_OPTIONS_RENAMES),
    )
    joined["has_usable_put_candidate"] = joined["ticker"].map(
        lambda ticker: _has_usable_slots(option_data.candidate_slots.get(str(ticker), []))
    )
    joined["has_usable_call_candidate"] = joined["ticker"].map(
        lambda ticker: _has_usable_slots(option_data.call_candidate_slots.get(str(ticker), []))
    )
    _ensure_configured_source_fields(joined, app_config.candidate_finder)
    result = joined.sort_values("ticker").reset_index(drop=True)
    warnings = _joined_frame_health_warnings(result, app_config.candidate_finder)
    if warnings:
        result.attrs["candidate_finder_join_warnings"] = tuple(warnings)
    return result


_TOOL_A_RENAMES = {
    "as_of_date": "tool_a_as_of_date",
    "snapshot_refresh_run_id": "tool_a_snapshot_refresh_run_id",
    "source_run_id": "tool_a_source_run_id",
}
_TOOL_B_RENAMES = {
    "as_of_date": "tool_b_as_of_date",
    "snapshot_refresh_run_id": "tool_b_snapshot_refresh_run_id",
    "source_run_id": "tool_b_source_run_id",
    "confidence": "tool_b_confidence",
}
_TOOL_C_RENAMES = {
    "as_of_date": "tool_c_as_of_date",
    "source_run_id": "tool_c_source_run_id",
    "snapshot_refresh_run_id": "tool_c_snapshot_refresh_run_id",
}
_TOOL_D_RENAMES = {
    "as_of_date": "tool_d_as_of_date",
    "source_run_id": "tool_d_source_run_id",
    "snapshot_refresh_run_id": "tool_d_snapshot_refresh_run_id",
}
_OPTIONS_RENAMES = {
    "as_of_date": "options_as_of_date",
    "run_id": "options_run_id",
    "options_fetch_status": "options_fetch_status",
    "options_fetch_message": "options_fetch_message",
}
_MANUAL_RENAMES = {
    "created_at_utc": "manual_created_at_utc",
    "updated_at_utc": "manual_updated_at_utc",
}

# Minimal core ranking columns a manifest-resolved CURRENT source must carry for
# the Candidate Finder to trust it. Keyed by the read label. Tool B has its own
# richer schema validator (validate_tool_b_output_schema); these anchor the other
# three dimensions so a readable-but-wrong artifact 503s instead of silently
# collapsing to a ticker-only frame (Codex options-UI review). Verified present in
# the live tool_a / tool_c / tool_d artifacts.
_FINDER_REQUIRED_SOURCE_COLUMNS: dict[str, tuple[str, ...]] = {
    "Gold Sensitivity": ("down_beta_core", "up_beta_core", "structural_delta_core"),
    "Gold Downside": ("tool_c_downside_rank", "tool_c_upside_rank"),
    "Corporate Resilience": ("tool_d_quality_rank",),
}


def _prepare_source(frame: pd.DataFrame, *, rename: dict[str, str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame({"ticker": pd.Series(dtype="object")})
    result = frame.copy()
    if "ticker" not in result.columns:
        return pd.DataFrame({"ticker": pd.Series(dtype="object")})
    result["ticker"] = result["ticker"].astype(str).str.upper().str.strip()
    result = result[result["ticker"] != ""].drop_duplicates(subset=["ticker"], keep="last")
    return result.rename(columns=rename)


def _merge_source(joined: pd.DataFrame, source: pd.DataFrame) -> pd.DataFrame:
    duplicate_columns = [
        column
        for column in source.columns
        if column != "ticker" and column in joined.columns
    ]
    if duplicate_columns:
        source = source.drop(columns=duplicate_columns)
    return joined.merge(source, how="left", on="ticker")


def _joined_frame_warnings(frame: pd.DataFrame) -> tuple[str, ...]:
    return tuple(frame.attrs.get("candidate_finder_join_warnings", ()) or ())


def _joined_frame_health_warnings(
    frame: pd.DataFrame,
    config: CandidateFinderConfig,
) -> list[str]:
    warnings: list[str] = []
    collision_columns = sorted(
        column
        for column in frame.columns
        if column.endswith("_x") or column.endswith("_y")
    )
    if collision_columns:
        warnings.append(
            "Candidate Finder source join produced duplicate-suffix columns; "
            "configured fields may be reading the wrong source: "
            + ", ".join(collision_columns)
            + "."
        )

    null_fields = []
    for criterion in config.criteria:
        column = criterion.source_field
        if column in frame.columns and frame[column].isna().all():
            null_fields.append(column)
    if null_fields:
        warnings.append(
            "Candidate Finder configured source fields are entirely null after "
            "source join: "
            + ", ".join(sorted(set(null_fields)))
            + "."
        )
    return warnings


def _ensure_configured_source_fields(
    frame: pd.DataFrame,
    config: CandidateFinderConfig,
) -> None:
    for criterion in config.criteria:
        if criterion.source_field not in frame.columns:
            frame[criterion.source_field] = pd.NA


def _has_usable_slots(slots: object) -> bool:
    return has_usable_option_slots(slots)


def _options_side(
    spec: Mapping[str, Any],
    *,
    preset: CandidateFinderPreset | None,
    warnings: list[str],
) -> OptionsSide:
    raw = str(spec.get("options_side") or "").strip().lower()
    if raw in {"puts", "calls", "either", "none"}:
        return raw  # type: ignore[return-value]
    if raw:
        warnings.append(f"Invalid options_side ignored: {raw}.")
    if preset is not None:
        return preset.options_side
    return "either"


def _apply_options_filter(frame: pd.DataFrame, *, options_side: OptionsSide) -> pd.DataFrame:
    if options_side == "none":
        return frame.copy()
    if frame.empty:
        return frame.copy()
    put_mask = frame["has_usable_put_candidate"].fillna(False).astype(bool)
    call_mask = frame["has_usable_call_candidate"].fillna(False).astype(bool)
    if options_side == "puts":
        return frame[put_mask].copy()
    if options_side == "calls":
        return frame[call_mask].copy()
    return frame[put_mask | call_mask].copy()


def _top_n(
    spec: Mapping[str, Any],
    config: CandidateFinderConfig,
    *,
    warnings: list[str],
) -> int:
    if "top_n" not in spec:
        return config.default_top_n
    try:
        value = int(spec["top_n"])
    except (TypeError, ValueError):
        warnings.append(
            f"Invalid top_n ignored: {spec.get('top_n')!r}; using {config.default_top_n}."
        )
        return config.default_top_n
    if value <= 0:
        warnings.append(f"Invalid top_n ignored: {value}; using {config.default_top_n}.")
        return config.default_top_n
    return value


def _selections(
    spec: Mapping[str, Any],
    *,
    preset: CandidateFinderPreset | None,
    warnings: list[str],
) -> list[CriterionSelection]:
    raw_criteria = spec.get("criteria")
    if raw_criteria is None:
        if preset is not None:
            return [_selection_from_preset(item) for item in preset.criteria]
        raw_criteria = []
    if not isinstance(raw_criteria, list):
        warnings.append("Invalid criteria ignored: expected a list.")
        return []
    return [_selection_from_raw(item) for item in raw_criteria]


def _selection_from_preset(item: CandidateFinderPresetCriterion) -> CriterionSelection:
    return CriterionSelection(
        id=item.id,
        direction=item.direction,
        weight=item.weight,
    )


def _selection_from_raw(item: object) -> CriterionSelection:
    if isinstance(item, str):
        return CriterionSelection(id=item)
    if isinstance(item, Mapping):
        return CriterionSelection(
            id=str(item.get("id", "")),
            direction=item.get("direction"),  # type: ignore[arg-type]
            weight=item.get("weight"),  # type: ignore[arg-type]
        )
    return CriterionSelection(id="")


def _preset(spec: Mapping[str, Any], config: CandidateFinderConfig):
    preset_id = _preset_id(spec)
    if not preset_id:
        return None
    return next((preset for preset in config.presets if preset.id == preset_id), None)


def _preset_id(spec: Mapping[str, Any]) -> str:
    return str(spec.get("preset") or "").strip()


def _alignment(
    *,
    model_state_manifest: dict[str, Any] | None,
    tool_a: pd.DataFrame,
    tool_b: pd.DataFrame,
    tool_c: pd.DataFrame,
    tool_d: pd.DataFrame,
    options_refresh_run_id: str | None,
    manual_store_hash: str | None,
    manual_store_as_of: str | None,
    source_load_warnings: tuple[str, ...] = (),
    scenario_active: bool = False,
) -> CandidateFinderAlignment:
    tool_a_ids = _unique_strings(tool_a, "snapshot_refresh_run_id")
    tool_b_ids = _unique_strings(tool_b, "snapshot_refresh_run_id")
    tool_c_ids = _unique_strings(tool_c, "snapshot_refresh_run_id")
    tool_d_ids = _unique_strings(tool_d, "snapshot_refresh_run_id")
    options_id = str(options_refresh_run_id or "").strip() or None
    source_ids: dict[str, tuple[str, ...]] = {
        "Gold Sensitivity": tool_a_ids,
        "Corporate Finance": tool_b_ids,
        "Gold Downside": tool_c_ids,
        "Corporate Resilience": tool_d_ids,
        "Options": (options_id,) if options_id else (),
    }
    missing = [name for name, values in source_ids.items() if not values]
    seen = {value for values in source_ids.values() for value in values}
    warnings = list(source_load_warnings)
    if not scenario_active:
        # Scenario Tool B/Tool D are always recomputed from the live manual
        # store, so the "manual store updated after the latest run" warning
        # would be misleading there.
        manual_warning = _manual_freshness_warning(
            tool_b=tool_b,
            manual_store_as_of=manual_store_as_of,
        )
        if manual_warning is not None:
            warnings.append(manual_warning)
    manifest_alignment = summarize_model_state_alignment(model_state_manifest)
    if manifest_alignment is not None:
        manifest_status_raw = str(manifest_alignment.get("status") or "UNKNOWN")
        if manifest_status_raw == "OK":
            manifest_status: Literal["OK", "WARN", "UNKNOWN"] = "OK"
        elif manifest_status_raw == "WARN":
            manifest_status = "WARN"
        else:
            manifest_status = "UNKNOWN"
        manifest_messages = [
            str(message)
            for message in manifest_alignment.get("warnings", ())
            if str(message).strip()
        ]
        alignment_warnings = _dedupe_alignment_messages(
            [*manifest_messages, *warnings]
        )
        if alignment_warnings:
            status = "WARN" if manifest_status == "OK" else manifest_status
            return CandidateFinderAlignment(
                status=status,
                message=alignment_warnings[0],
                tool_a_refresh_run_ids=tool_a_ids,
                tool_b_refresh_run_ids=tool_b_ids,
                tool_c_refresh_run_ids=tool_c_ids,
                tool_d_refresh_run_ids=tool_d_ids,
                options_refresh_run_id=options_id,
                manual_store_hash=manual_store_hash,
                manual_store_as_of=manual_store_as_of,
                messages=tuple(alignment_warnings),
            )
        return CandidateFinderAlignment(
            status="OK",
            message=None,
            tool_a_refresh_run_ids=tool_a_ids,
            tool_b_refresh_run_ids=tool_b_ids,
            tool_c_refresh_run_ids=tool_c_ids,
            tool_d_refresh_run_ids=tool_d_ids,
            options_refresh_run_id=options_id,
            manual_store_hash=manual_store_hash,
            manual_store_as_of=manual_store_as_of,
            messages=(),
        )
    if missing:
        message = "Missing refresh ids for: " + ", ".join(missing) + "."
        return CandidateFinderAlignment(
            status="UNKNOWN",
            message=message,
            tool_a_refresh_run_ids=tool_a_ids,
            tool_b_refresh_run_ids=tool_b_ids,
            tool_c_refresh_run_ids=tool_c_ids,
            tool_d_refresh_run_ids=tool_d_ids,
            options_refresh_run_id=options_id,
            manual_store_hash=manual_store_hash,
            manual_store_as_of=manual_store_as_of,
            messages=tuple([message, *warnings]),
        )
    if len(seen) > 1:
        parts = [
            f"{name}: {', '.join(values)}"
            for name, values in source_ids.items()
            if values
        ]
        message = "Mixed refreshes in Candidate Finder sources (" + "; ".join(parts) + ")."
        return CandidateFinderAlignment(
            status="WARN",
            message=message,
            tool_a_refresh_run_ids=tool_a_ids,
            tool_b_refresh_run_ids=tool_b_ids,
            tool_c_refresh_run_ids=tool_c_ids,
            tool_d_refresh_run_ids=tool_d_ids,
            options_refresh_run_id=options_id,
            manual_store_hash=manual_store_hash,
            manual_store_as_of=manual_store_as_of,
            messages=tuple([message, *warnings]),
        )
    if warnings:
        message = warnings[0]
        return CandidateFinderAlignment(
            status="WARN",
            message=message,
            tool_a_refresh_run_ids=tool_a_ids,
            tool_b_refresh_run_ids=tool_b_ids,
            tool_c_refresh_run_ids=tool_c_ids,
            tool_d_refresh_run_ids=tool_d_ids,
            options_refresh_run_id=options_id,
            manual_store_hash=manual_store_hash,
            manual_store_as_of=manual_store_as_of,
            messages=tuple(warnings),
        )
    return CandidateFinderAlignment(
        status="OK",
        message=None,
        tool_a_refresh_run_ids=tool_a_ids,
        tool_b_refresh_run_ids=tool_b_ids,
        tool_c_refresh_run_ids=tool_c_ids,
        tool_d_refresh_run_ids=tool_d_ids,
        options_refresh_run_id=options_id,
        manual_store_hash=manual_store_hash,
        manual_store_as_of=manual_store_as_of,
        messages=(),
    )


def _dedupe_alignment_messages(values: list[str]) -> list[str]:
    messages: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        messages.append(text)
    return messages


def _options_refresh_run_id(option_data: OptionTradingData) -> str | None:
    context = option_data.overview.source_context
    if context is not None and context.refresh_run_id:
        return str(context.refresh_run_id)
    if option_data.cache_key is not None:
        return option_data.cache_key.options_refresh_run_id
    return None


def _manual_as_of(company_inputs: pd.DataFrame) -> str | None:
    if company_inputs.empty or "updated_at_utc" not in company_inputs.columns:
        return None
    values = company_inputs["updated_at_utc"].dropna().astype(str)
    if values.empty:
        return None
    return str(values.max())


def _manual_freshness_warning(
    *,
    tool_b: pd.DataFrame,
    manual_store_as_of: str | None,
) -> str | None:
    manual_timestamp = _parse_timestamp(manual_store_as_of)
    tool_b_timestamp = _latest_tool_b_run_timestamp(tool_b)
    if manual_timestamp is None or tool_b_timestamp is None:
        return None
    if manual_timestamp <= tool_b_timestamp:
        return None
    return (
        "Manual store was updated after the latest Corporate Finance run; rerun Corporate Finance "
        "before relying on manual-dependent Candidate Finder criteria."
    )


def _latest_tool_b_run_timestamp(tool_b: pd.DataFrame) -> pd.Timestamp | None:
    if tool_b.empty:
        return None
    candidates: list[pd.Timestamp] = []
    if "source_run_id" in tool_b.columns:
        for value in tool_b["source_run_id"].dropna().astype(str).unique():
            parsed = _parse_run_id_timestamp(value)
            if parsed is not None:
                candidates.append(parsed)
    if candidates:
        return max(candidates)
    if "snapshot_refresh_run_id" in tool_b.columns:
        for value in tool_b["snapshot_refresh_run_id"].dropna().astype(str).unique():
            parsed = _parse_run_id_timestamp(value)
            if parsed is not None:
                candidates.append(parsed)
    return max(candidates) if candidates else None


def _parse_run_id_timestamp(value: object) -> pd.Timestamp | None:
    text = str(value or "").strip()
    if len(text) < 16:
        return None
    return _parse_timestamp(text[:16])


def _parse_timestamp(value: object) -> pd.Timestamp | None:
    if value is None:
        return None
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return parsed


def _read_optional_parquet(
    path: Path | None, *, label: str, required: bool = False
) -> CandidateFinderSourceLoad:
    if path is None or not path.exists():
        return CandidateFinderSourceLoad(frame=pd.DataFrame())
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        if required:
            # A MANIFEST-resolved current artifact is corrupt/unreadable. A warning
            # banner is not enough -- a missing dimension can leave the ranking
            # looking usable but wrong, so fail loud and let the route render a
            # friendly refresh page (audit M7).
            raise CandidateFinderSourceError(
                f"{label} current artifact at {path} could not be read: {exc}."
            ) from exc
        # Legacy/no-manifest fallback alias: tolerate with a warning (transition path).
        return CandidateFinderSourceLoad(
            frame=pd.DataFrame(),
            warning=f"{label} latest parquet could not be read: {exc}.",
        )
    if label == "Corporate Finance":
        frame = validate_tool_b_output_schema(
            frame,
            label="Candidate Finder Corporate Finance artifact",
        )
    elif required and label in _FINDER_REQUIRED_SOURCE_COLUMNS:
        # A MANIFEST-resolved current Tool A/C/D artifact that READS but is missing
        # its core ranking columns would otherwise flow through _prepare_source,
        # collapse to a ticker-only frame, and leave a whole dimension silently
        # null behind only a warning. That is the same "looks usable but wrong"
        # failure M7 closed for unreadable sources -- so fail loud here too and let
        # the route render the friendly refresh page (Codex options-UI review).
        missing_columns = [
            column
            for column in _FINDER_REQUIRED_SOURCE_COLUMNS[label]
            if column not in frame.columns
        ]
        if missing_columns:
            raise CandidateFinderSourceError(
                f"{label} current artifact at {path} is missing required ranking "
                f"columns ({', '.join(missing_columns)}); a manifest-resolved current "
                "source must carry them or the Candidate Finder would silently drop a "
                "whole dimension."
            )
    return CandidateFinderSourceLoad(frame=frame)


def _compute_scenario_sources(
    *,
    paths: ProjectPaths,
    app_config: AppConfig,
    scenario: CandidateFinderScenario,
    foundation_manifest_path: Path | None,
) -> _CandidateFinderScenarioSources:
    foundation_snapshot = load_latest_foundation_snapshot(
        paths=paths,
        app_config=app_config,
        include_gold_history=True,
        include_equity_histories=False,
        include_market_snapshots=True,
        manifest_path=foundation_manifest_path,
    )
    spot_gold_usd, spot_gold_date = latest_gold_price_from_history(
        foundation_snapshot.gold_history
    )
    gold_price_basis = (
        "latest_daily_gold_close"
        if abs(scenario.gold_price - spot_gold_usd) <= 0.01
        else "custom_scenario"
    )
    manual_data = load_manual_screening_data(
        paths,
        tickers=sorted(
            ticker.ticker
            for ticker in app_config.universe.tickers
            if ticker.active and ticker.tool_b_enabled
        ),
    )
    # The scenario recompute must use the SAME fundamentals inputs as the
    # persisted Tool B pipeline and the Tool B gold dial, or a scenario at
    # spot silently disagrees with the default screen for any ticker whose
    # net debt / EBITDA / D&A / interest exist only in the official store.
    official_fundamentals = load_official_fundamentals(paths)
    tool_b = validate_tool_b_output_schema(
        compute_tool_b_in_memory(
            app_config=app_config,
            manual_data=manual_data,
            normalized_market_snapshots=foundation_snapshot.normalized_market_snapshots,
            gold_price_assumption=scenario.gold_price,
            snapshot_refresh_run_id=foundation_snapshot.refresh_run_id,
            snapshot_as_of_date=foundation_snapshot.snapshot_as_of_date,
            source_run_id=_SCENARIO_SOURCE_RUN_ID,
            spot_gold_usd=spot_gold_usd,
            spot_gold_date=spot_gold_date,
            gold_price_basis=gold_price_basis,
            official_fundamentals=official_fundamentals,
        ),
        label="Candidate Finder scenario Corporate Finance frame",
    )
    tool_b_latest = validate_tool_b_output_schema(
        read_current_model_parquet(
            paths,
            "tool_b",
            fallback_path=paths.latest_tool_b_snapshot_parquet_path,
        ),
        label="Candidate Finder scenario persisted Corporate Finance input",
    )
    if tool_b_latest.empty:
        tool_b_latest = tool_b
    tool_d = compute_tool_d_outputs(
        inputs=ToolDExecutionInputs(
            app_config=app_config,
            manual_data=manual_data,
            normalized_market_snapshots=foundation_snapshot.normalized_market_snapshots,
            tool_b_latest=tool_b_latest,
            spot_gold_usd=spot_gold_usd,
            spot_gold_date=spot_gold_date,
            snapshot_refresh_run_id=foundation_snapshot.refresh_run_id,
            snapshot_as_of_date=foundation_snapshot.snapshot_as_of_date,
        ),
        config=app_config.tool_d,
        gold_price=scenario.gold_price,
        source_run_id=_SCENARIO_SOURCE_RUN_ID,
    )
    tool_d_load = _scenario_tool_d_source(
        tool_d,
        expected_gold_price=scenario.gold_price,
    )
    rank_basis = (
        "latest_daily_gold_close"
        if gold_price_basis == "latest_daily_gold_close"
        else "custom_gold_scenario"
    )
    return _CandidateFinderScenarioSources(
        tool_b=CandidateFinderSourceLoad(frame=tool_b),
        tool_d=tool_d_load,
        gold_price_used=float(scenario.gold_price),
        spot_gold_usd=float(spot_gold_usd),
        spot_gold_date=spot_gold_date,
        source_basis=gold_price_basis,
        rank_basis=rank_basis,
    )


def _spot_tool_b_source(frame: pd.DataFrame) -> CandidateFinderSourceLoad:
    if frame.empty:
        return CandidateFinderSourceLoad(frame=frame)
    required = {"gold_price_used", "spot_gold_usd", "gold_price_basis"}
    if not required.issubset(frame.columns):
        return CandidateFinderSourceLoad(
            frame=_blank_tool_b_gold_scenario_fields(frame),
            warning=(
                "Corporate Finance latest parquet does not record spot-gold provenance; "
                "Candidate Finder treats gold-dependent Corporate Finance criteria as missing "
                f"for affected tickers: {_ticker_sample(frame)}."
            ),
        )
    gold_price = pd.to_numeric(frame["gold_price_used"], errors="coerce")
    spot_gold = pd.to_numeric(frame["spot_gold_usd"], errors="coerce")
    basis = frame["gold_price_basis"].astype(str).str.strip()
    comparable = gold_price.notna() & spot_gold.notna()
    is_spot = comparable & gold_price.sub(spot_gold).abs().le(0.01) & basis.eq(
        "latest_daily_gold_close"
    )
    if bool(is_spot.all()):
        return CandidateFinderSourceLoad(frame=frame)
    return CandidateFinderSourceLoad(
        frame=_blank_tool_b_gold_scenario_fields(frame),
        warning=(
            "Corporate Finance latest parquet is not a spot-gold run; Candidate Finder "
            "treats gold-dependent Corporate Finance criteria as missing until spot "
            f"Corporate Finance is rerun. Off-spot tickers: {_ticker_sample(frame.loc[~is_spot])}."
        ),
    )


def _resolve_finder_source(
    paths: ProjectPaths, name: str, *, fallback_path: Path | None
) -> tuple[Path | None, bool]:
    """Resolve a Candidate Finder source path and whether it is required.

    A manifest-resolved current artifact is required: a corrupt read fails loud
    (audit M7). A latest-alias fallback used only because there is no manifest entry
    is a legacy/transition path: a corrupt read degrades to a warning, not a crash.
    """

    manifest_path = resolve_current_model_artifact_path(paths, name)
    if manifest_path is not None:
        return manifest_path, True
    if fallback_path is not None and fallback_path.exists():
        return fallback_path, False
    return None, False


def _tool_d_finder_source(paths: ProjectPaths) -> tuple[Path | None, bool]:
    spot_path, spot_required = _resolve_finder_source(
        paths, "tool_d_spot", fallback_path=paths.latest_tool_d_spot_snapshot_parquet_path
    )
    if spot_path is not None:
        return spot_path, spot_required
    return _resolve_finder_source(
        paths, "tool_d", fallback_path=paths.latest_tool_d_snapshot_parquet_path
    )


def _spot_tool_d_source(frame: pd.DataFrame) -> CandidateFinderSourceLoad:
    if frame.empty:
        return CandidateFinderSourceLoad(frame=frame)
    required = {"gold_price_used", "spot_gold_usd"}
    if not required.issubset(frame.columns):
        return CandidateFinderSourceLoad(
            frame=_blank_tool_d_finder_fields(frame),
            warning=(
                "Corporate Resilience latest parquet does not record spot-gold provenance; "
                "Candidate Finder treats Corporate Resilience criteria as missing "
                f"for affected tickers: {_ticker_sample(frame)}."
            ),
        )
    gold_price = pd.to_numeric(frame["gold_price_used"], errors="coerce")
    spot_gold = pd.to_numeric(frame["spot_gold_usd"], errors="coerce")
    comparable = gold_price.notna() & spot_gold.notna()
    is_spot = comparable & gold_price.sub(spot_gold).abs().le(0.01)
    if bool(is_spot.all()):
        return CandidateFinderSourceLoad(frame=frame)
    return CandidateFinderSourceLoad(
        frame=_blank_tool_d_finder_fields(frame),
        warning=(
            "Corporate Resilience latest parquet is not a spot-gold run; Candidate Finder "
            "treats Corporate Resilience criteria as missing until spot Corporate "
            f"Resilience is rerun. Off-spot tickers: {_ticker_sample(frame.loc[~is_spot])}."
        ),
    )


def _scenario_tool_d_source(
    frame: pd.DataFrame,
    *,
    expected_gold_price: float,
) -> CandidateFinderSourceLoad:
    if frame.empty:
        return CandidateFinderSourceLoad(frame=frame)
    if "gold_price_used" not in frame.columns:
        return CandidateFinderSourceLoad(
            frame=_blank_tool_d_finder_fields(frame),
            warning=(
                "Candidate Finder scenario Corporate Resilience frame does not record "
                "gold-price provenance; Corporate Resilience criteria were withheld."
            ),
        )
    gold_price = pd.to_numeric(frame["gold_price_used"], errors="coerce")
    is_expected = gold_price.notna() & gold_price.sub(float(expected_gold_price)).abs().le(0.01)
    if bool(is_expected.all()):
        return CandidateFinderSourceLoad(frame=frame)
    return CandidateFinderSourceLoad(
        frame=_blank_tool_d_finder_fields(frame),
        warning=(
            "Candidate Finder scenario Corporate Resilience frame was computed at the wrong "
            "gold price; Corporate Resilience criteria were withheld."
        ),
    )


def _blank_tool_b_gold_scenario_fields(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in TOOL_B_GOLD_SCENARIO_FIELDS:
        if column in result.columns:
            result[column] = pd.NA
    return result


def _blank_tool_d_finder_fields(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in TOOL_D_FINDER_FIELDS:
        if column in result.columns:
            result[column] = pd.NA
    return result


def _first_provenance_number(column: str, *frames: pd.DataFrame) -> float | None:
    for frame in frames:
        value = _first_frame_number(frame, column)
        if value is not None:
            return value
    return None


def _first_provenance_text(column: str, *frames: pd.DataFrame) -> str | None:
    for frame in frames:
        if frame.empty or column not in frame.columns:
            continue
        values = frame[column].dropna()
        if values.empty:
            continue
        text = str(values.iloc[0]).strip()
        if text:
            return text
    return None


def _cache_gold_price(scenario: CandidateFinderScenario | None) -> float | None:
    if scenario is None:
        return None
    return round(float(scenario.gold_price), 4)


def _cache_get(cache_key: CandidateFinderCacheKey) -> CandidateFinderData | None:
    cached = _CACHE.get(cache_key)
    if cached is None:
        return None
    _CACHE.move_to_end(cache_key)
    return cached


def _cache_set(cache_key: CandidateFinderCacheKey, data: CandidateFinderData) -> None:
    _CACHE[cache_key] = data
    _CACHE.move_to_end(cache_key)
    while len(_CACHE) > _CACHE_MAX_SIZE:
        _CACHE.popitem(last=False)


def _ticker_sample(frame: pd.DataFrame, *, limit: int = 5) -> str:
    if frame.empty or "ticker" not in frame.columns:
        return "the affected rows"
    tickers = [
        str(value).upper().strip()
        for value in frame["ticker"].dropna().tolist()
        if str(value).strip()
    ]
    if not tickers:
        return "the affected rows"
    unique = _common_unique_strings(pd.DataFrame({"ticker": tickers}), "ticker")
    displayed = unique[:limit]
    suffix = "" if len(unique) <= limit else f" +{len(unique) - limit} more"
    return ", ".join(displayed) + suffix


def _unique_strings(frame: pd.DataFrame, column: str) -> tuple[str, ...]:
    return tuple(_common_unique_strings(frame, column))
