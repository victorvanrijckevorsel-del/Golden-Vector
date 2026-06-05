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
    CandidateFinderPreset,
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
    tool_c_refresh_run_ids: tuple[str, ...]
    tool_d_refresh_run_ids: tuple[str, ...]
    options_refresh_run_id: str
    manual_store_hash: str | None
    tool_a_latest_hash: str | None
    tool_b_latest_hash: str | None
    tool_c_latest_hash: str | None
    tool_d_latest_hash: str | None


@dataclass(frozen=True)
class CandidateFinderSourceLoad:
    frame: pd.DataFrame
    warning: str | None = None


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

    tool_a_load = _read_optional_parquet(
        paths.latest_tool_a_snapshot_parquet_path,
        label="Tool A",
    )
    tool_b_load = _read_optional_parquet(
        paths.latest_tool_b_snapshot_parquet_path,
        label="Tool B",
    )
    tool_a = tool_a_load.frame
    tool_b = tool_b_load.frame
    tool_c_load = _read_optional_parquet(
        paths.latest_tool_c_snapshot_parquet_path,
        label="Tool C",
    )
    tool_d_source_path = _tool_d_finder_source_path(paths)
    tool_d_load = _read_optional_parquet(
        tool_d_source_path,
        label="Tool D",
    )
    tool_c = tool_c_load.frame
    tool_d_spot_load = _spot_tool_d_source(tool_d_load.frame)
    tool_d = tool_d_spot_load.frame
    option_data = load_option_trading_data(paths, app_config=app_config)
    manual_company, _, _, _ = load_store_tables(paths)
    manual_hash = _file_sha256(paths.manual_screening_store_path)
    manual_as_of = _manual_as_of(manual_company)
    options_refresh_run_id = _options_refresh_run_id(option_data)
    cache_key = CandidateFinderCacheKey(
        tool_a_refresh_run_ids=_unique_strings(tool_a, "snapshot_refresh_run_id"),
        tool_b_refresh_run_ids=_unique_strings(tool_b, "snapshot_refresh_run_id"),
        tool_c_refresh_run_ids=_unique_strings(tool_c, "snapshot_refresh_run_id"),
        tool_d_refresh_run_ids=_unique_strings(tool_d, "snapshot_refresh_run_id"),
        options_refresh_run_id=options_refresh_run_id or "unknown",
        manual_store_hash=manual_hash,
        tool_a_latest_hash=_file_sha256(paths.latest_tool_a_snapshot_parquet_path),
        tool_b_latest_hash=_file_sha256(paths.latest_tool_b_snapshot_parquet_path),
        tool_c_latest_hash=_file_sha256(paths.latest_tool_c_snapshot_parquet_path),
        tool_d_latest_hash=_file_sha256(tool_d_source_path),
    )
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached

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
        tool_a=tool_a,
        tool_b=tool_b,
        tool_c=tool_c,
        tool_d=tool_d,
        options_refresh_run_id=options_refresh_run_id,
        manual_store_hash=manual_hash,
        manual_store_as_of=manual_as_of,
        source_load_warnings=tuple(
            warning
            for warning in (
                tool_a_load.warning,
                tool_b_load.warning,
                tool_c_load.warning,
                tool_d_load.warning,
                tool_d_spot_load.warning,
            )
            if warning is not None
        ),
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
        _prepare_source(tool_c, rename=_TOOL_C_RENAMES),
        how="left",
        on="ticker",
    )
    joined = joined.merge(
        _prepare_source(tool_d, rename=_TOOL_D_RENAMES),
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
    _ensure_configured_source_fields(joined, app_config.candidate_finder)
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


def _ensure_configured_source_fields(
    frame: pd.DataFrame,
    config: CandidateFinderConfig,
) -> None:
    for criterion in config.criteria:
        if criterion.source_field not in frame.columns:
            frame[criterion.source_field] = pd.NA


def _numeric_source_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([pd.NA] * len(frame.index), index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _ratio_series(values: pd.Series, denominator: pd.Series) -> pd.Series:
    result = values / denominator
    result = result.where(denominator > 0)
    return result.where(values.notna())


def _has_usable_slots(slots: object) -> bool:
    return any(
        getattr(getattr(slot, "candidate", None), "liquidity_tier", None) == "tradable"
        for slot in slots or []
    )


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
    tool_a: pd.DataFrame,
    tool_b: pd.DataFrame,
    tool_c: pd.DataFrame,
    tool_d: pd.DataFrame,
    options_refresh_run_id: str | None,
    manual_store_hash: str | None,
    manual_store_as_of: str | None,
    source_load_warnings: tuple[str, ...] = (),
) -> CandidateFinderAlignment:
    tool_a_ids = _unique_strings(tool_a, "snapshot_refresh_run_id")
    tool_b_ids = _unique_strings(tool_b, "snapshot_refresh_run_id")
    tool_c_ids = _unique_strings(tool_c, "snapshot_refresh_run_id")
    tool_d_ids = _unique_strings(tool_d, "snapshot_refresh_run_id")
    options_id = str(options_refresh_run_id or "").strip() or None
    source_ids: dict[str, tuple[str, ...]] = {
        "Tool A": tool_a_ids,
        "Tool B": tool_b_ids,
        "Tool C": tool_c_ids,
        "Tool D": tool_d_ids,
        "Options": (options_id,) if options_id else (),
    }
    missing = [name for name, values in source_ids.items() if not values]
    seen = {value for values in source_ids.values() for value in values}
    warnings = list(source_load_warnings)
    manual_warning = _manual_freshness_warning(
        tool_b=tool_b,
        manual_store_as_of=manual_store_as_of,
    )
    if manual_warning is not None:
        warnings.append(manual_warning)
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
        "Manual store was updated after the latest Tool B run; rerun Tool B "
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


def _file_sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_optional_parquet(path: Path, *, label: str) -> CandidateFinderSourceLoad:
    if not path.exists():
        return CandidateFinderSourceLoad(frame=pd.DataFrame())
    try:
        return CandidateFinderSourceLoad(frame=pd.read_parquet(path))
    except Exception as exc:
        return CandidateFinderSourceLoad(
            frame=pd.DataFrame(),
            warning=f"{label} latest parquet could not be read: {exc}.",
        )


def _tool_d_finder_source_path(paths: ProjectPaths) -> Path:
    spot_path = paths.latest_tool_d_spot_snapshot_parquet_path
    return spot_path if spot_path.exists() else paths.latest_tool_d_snapshot_parquet_path


def _spot_tool_d_source(frame: pd.DataFrame) -> CandidateFinderSourceLoad:
    if frame.empty:
        return CandidateFinderSourceLoad(frame=frame)
    required = {"gold_price_used", "spot_gold_usd"}
    if not required.issubset(frame.columns):
        return CandidateFinderSourceLoad(
            frame=_blank_tool_d_quality(frame),
            warning=(
                "Tool D latest parquet does not record spot-gold provenance; "
                "Candidate Finder treats Tool D quality rank as missing."
            ),
        )
    gold_price = pd.to_numeric(frame["gold_price_used"], errors="coerce")
    spot_gold = pd.to_numeric(frame["spot_gold_usd"], errors="coerce")
    comparable = gold_price.notna() & spot_gold.notna()
    is_spot = comparable & gold_price.sub(spot_gold).abs().le(0.01)
    if bool(is_spot.all()):
        return CandidateFinderSourceLoad(frame=frame)
    return CandidateFinderSourceLoad(
        frame=_blank_tool_d_quality(frame),
        warning=(
            "Tool D latest parquet is not a spot-gold run; Candidate Finder "
            "treats Tool D quality rank as missing until spot Tool D is rerun."
        ),
    )


def _blank_tool_d_quality(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if "tool_d_quality_rank" in result.columns:
        result["tool_d_quality_rank"] = pd.NA
    return result


def _unique_strings(frame: pd.DataFrame, column: str) -> tuple[str, ...]:
    if frame.empty or column not in frame.columns:
        return ()
    values = {
        str(value).strip()
        for value in frame[column].dropna().unique()
        if str(value).strip() and str(value).strip().lower() != "nan"
    }
    return tuple(sorted(values))
