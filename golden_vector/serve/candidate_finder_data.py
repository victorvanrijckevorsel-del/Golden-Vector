"""Data loading and screen execution for the Candidate Finder."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import yaml

from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.config_models import (
    AppConfig,
    CandidateFinderConfig,
    CandidateFinderPresetCriterion,
)
from golden_vector.model.candidate_finder import (
    CandidateFinderResult,
    CriterionSelection,
    rank_candidates,
)
from golden_vector.screening.manual_store import load_store_tables
from golden_vector.serve.option_trading_data import (
    OptionTradingData,
    load_option_trading_data,
)

OptionsSide = Literal["puts", "calls", "either", "none"]


@dataclass(frozen=True)
class CandidateFinderCacheKey:
    tool_a_refresh_run_ids: tuple[str, ...]
    tool_b_refresh_run_ids: tuple[str, ...]
    options_refresh_run_id: str
    manual_store_hash: str | None


@dataclass(frozen=True)
class CandidateFinderAlignment:
    status: Literal["OK", "WARN", "UNKNOWN"]
    message: str | None
    tool_a_refresh_run_ids: tuple[str, ...]
    tool_b_refresh_run_ids: tuple[str, ...]
    options_refresh_run_id: str | None
    manual_store_hash: str | None
    manual_store_as_of: str | None


@dataclass(frozen=True)
class CandidateFinderData:
    frame: pd.DataFrame
    criteria_config: CandidateFinderConfig
    alignment: CandidateFinderAlignment
    cache_key: CandidateFinderCacheKey


@dataclass(frozen=True)
class CandidateFinderScreen:
    data: CandidateFinderData
    ranking: CandidateFinderResult
    peer_frame: pd.DataFrame
    options_side: OptionsSide
    top_n: int
    warnings: tuple[str, ...]


_CACHE: dict[CandidateFinderCacheKey, CandidateFinderData] = {}


def clear_candidate_finder_cache() -> None:
    _CACHE.clear()


def load_candidate_finder_data(
    paths: ProjectPaths,
    *,
    app_config: AppConfig,
) -> CandidateFinderData:
    """Load the latest joined frame used by Candidate Finder screens."""

    tool_a = _read_optional_parquet(paths.latest_tool_a_snapshot_parquet_path)
    tool_b = _read_optional_parquet(paths.latest_tool_b_snapshot_parquet_path)
    option_data = load_option_trading_data(paths, app_config=app_config)
    manual_company, _, _, _ = load_store_tables(paths)
    manual_hash = _file_sha256(paths.manual_screening_store_path)
    manual_as_of = _manual_as_of(manual_company)
    options_refresh_run_id = _options_refresh_run_id(option_data)
    cache_key = CandidateFinderCacheKey(
        tool_a_refresh_run_ids=_unique_strings(tool_a, "snapshot_refresh_run_id"),
        tool_b_refresh_run_ids=_unique_strings(tool_b, "snapshot_refresh_run_id"),
        options_refresh_run_id=options_refresh_run_id or "unknown",
        manual_store_hash=manual_hash,
    )
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached

    frame = _joined_frame(
        app_config=app_config,
        tool_a=tool_a,
        tool_b=tool_b,
        options=option_data.options_features,
        manual_company=manual_company,
        option_data=option_data,
    )
    alignment = _alignment(
        tool_a=tool_a,
        tool_b=tool_b,
        options_refresh_run_id=options_refresh_run_id,
        manual_store_hash=manual_hash,
        manual_store_as_of=manual_as_of,
    )
    data = CandidateFinderData(
        frame=frame,
        criteria_config=app_config.candidate_finder,
        alignment=alignment,
        cache_key=cache_key,
    )
    _CACHE[cache_key] = data
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
    options_side = _options_side(screen_spec, data.criteria_config)
    peer_frame = _apply_options_filter(data.frame, options_side=options_side)
    top_n = _top_n(screen_spec, data.criteria_config)
    selections = _selections(screen_spec, data.criteria_config)
    ranking = rank_candidates(
        peer_frame,
        criteria=list(data.criteria_config.criteria),
        selections=selections,
        top_n=top_n,
        min_criteria_fraction=data.criteria_config.min_criteria_fraction,
    )
    warnings = list(ranking.warnings)
    if data.alignment.status != "OK":
        warnings.insert(0, data.alignment.message or "Candidate Finder sources are not aligned.")
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
    joined = joined.merge(
        _prepare_source(tool_a, rename=_TOOL_A_RENAMES),
        how="left",
        on="ticker",
    )
    joined = joined.merge(
        _prepare_source(tool_b, rename=_TOOL_B_RENAMES),
        how="left",
        on="ticker",
    )
    joined = joined.merge(
        _prepare_source(options, rename=_OPTIONS_RENAMES),
        how="left",
        on="ticker",
    )
    joined = joined.merge(
        _prepare_source(manual_company, rename=_MANUAL_RENAMES),
        how="left",
        on="ticker",
    )
    joined["has_usable_put_candidate"] = joined["ticker"].map(
        lambda ticker: _has_usable_slots(option_data.candidate_slots.get(str(ticker), []))
    )
    joined["has_usable_call_candidate"] = joined["ticker"].map(
        lambda ticker: _has_usable_slots(option_data.call_candidate_slots.get(str(ticker), []))
    )
    _add_derived_ratios(joined)
    return joined.sort_values("ticker").reset_index(drop=True)


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


def _prepare_source(frame: pd.DataFrame, *, rename: dict[str, str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame({"ticker": pd.Series(dtype="object")})
    result = frame.copy()
    if "ticker" not in result.columns:
        return pd.DataFrame({"ticker": pd.Series(dtype="object")})
    result["ticker"] = result["ticker"].astype(str).str.upper().str.strip()
    result = result[result["ticker"] != ""].drop_duplicates(subset=["ticker"], keep="last")
    return result.rename(columns=rename)


def _add_derived_ratios(frame: pd.DataFrame) -> None:
    market_cap = _numeric_source_series(frame, "market_cap_musd")
    frame["debt_to_mktcap"] = _ratio_series(
        _numeric_source_series(frame, "net_debt_musd"),
        market_cap,
    )
    frame["ebitda_to_mktcap"] = _ratio_series(
        _numeric_source_series(frame, "forward_ebitda_musd"),
        market_cap,
    )
    frame["revenue_to_mktcap"] = _ratio_series(
        _numeric_source_series(frame, "forward_revenue_musd"),
        market_cap,
    )
    frame["netincome_to_mktcap"] = _ratio_series(
        _numeric_source_series(frame, "forward_net_income_musd"),
        market_cap,
    )


def _numeric_source_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([pd.NA] * len(frame.index), index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _ratio_series(values: pd.Series, denominator: pd.Series) -> pd.Series:
    result = values / denominator
    result = result.where(denominator > 0)
    return result.where(values.notna())


def _has_usable_slots(slots: object) -> bool:
    # Slot candidates are populated by build_bucket_slots() only after
    # is_usable_candidate() passes, so this reuses the shared options gate.
    return any(getattr(slot, "candidate", None) is not None for slot in slots or [])


def _options_side(
    spec: Mapping[str, Any],
    config: CandidateFinderConfig,
) -> OptionsSide:
    raw = str(spec.get("options_side") or "").strip().lower()
    if raw in {"puts", "calls", "either", "none"}:
        return raw  # type: ignore[return-value]
    preset = _preset(spec, config)
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


def _top_n(spec: Mapping[str, Any], config: CandidateFinderConfig) -> int:
    try:
        value = int(spec.get("top_n", config.default_top_n))
    except (TypeError, ValueError):
        return config.default_top_n
    return value if value > 0 else config.default_top_n


def _selections(
    spec: Mapping[str, Any],
    config: CandidateFinderConfig,
) -> list[CriterionSelection]:
    raw_criteria = spec.get("criteria")
    if raw_criteria is None:
        preset = _preset(spec, config)
        if preset is not None:
            return [_selection_from_preset(item) for item in preset.criteria]
        raw_criteria = []
    if not isinstance(raw_criteria, list):
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
    preset_id = str(spec.get("preset") or "").strip()
    if not preset_id:
        return None
    return next((preset for preset in config.presets if preset.id == preset_id), None)


def _alignment(
    *,
    tool_a: pd.DataFrame,
    tool_b: pd.DataFrame,
    options_refresh_run_id: str | None,
    manual_store_hash: str | None,
    manual_store_as_of: str | None,
) -> CandidateFinderAlignment:
    tool_a_ids = _unique_strings(tool_a, "snapshot_refresh_run_id")
    tool_b_ids = _unique_strings(tool_b, "snapshot_refresh_run_id")
    options_id = str(options_refresh_run_id or "").strip() or None
    source_ids: dict[str, tuple[str, ...]] = {
        "Tool A": tool_a_ids,
        "Tool B": tool_b_ids,
        "Options": (options_id,) if options_id else (),
    }
    missing = [name for name, values in source_ids.items() if not values]
    seen = {value for values in source_ids.values() for value in values}
    if missing:
        return CandidateFinderAlignment(
            status="UNKNOWN",
            message="Missing refresh ids for: " + ", ".join(missing) + ".",
            tool_a_refresh_run_ids=tool_a_ids,
            tool_b_refresh_run_ids=tool_b_ids,
            options_refresh_run_id=options_id,
            manual_store_hash=manual_store_hash,
            manual_store_as_of=manual_store_as_of,
        )
    if len(seen) > 1:
        parts = [
            f"{name}: {', '.join(values)}"
            for name, values in source_ids.items()
            if values
        ]
        return CandidateFinderAlignment(
            status="WARN",
            message="Mixed refreshes in Candidate Finder sources (" + "; ".join(parts) + ").",
            tool_a_refresh_run_ids=tool_a_ids,
            tool_b_refresh_run_ids=tool_b_ids,
            options_refresh_run_id=options_id,
            manual_store_hash=manual_store_hash,
            manual_store_as_of=manual_store_as_of,
        )
    return CandidateFinderAlignment(
        status="OK",
        message=None,
        tool_a_refresh_run_ids=tool_a_ids,
        tool_b_refresh_run_ids=tool_b_ids,
        options_refresh_run_id=options_id,
        manual_store_hash=manual_store_hash,
        manual_store_as_of=manual_store_as_of,
    )


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


def _file_sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_optional_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()


def _unique_strings(frame: pd.DataFrame, column: str) -> tuple[str, ...]:
    if frame.empty or column not in frame.columns:
        return ()
    values = {
        str(value).strip()
        for value in frame[column].dropna().unique()
        if str(value).strip() and str(value).strip().lower() != "nan"
    }
    return tuple(sorted(values))
