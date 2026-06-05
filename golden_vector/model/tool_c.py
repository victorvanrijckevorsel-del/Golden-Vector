"""Tool C symmetric behavior ranking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from golden_vector.common.eligibility import is_score_eligible, score_eligible_mask
from golden_vector.contracts.config_models import ToolCConfig
from golden_vector.features.gold_regime import build_gold_regime_frame
from golden_vector.features.percentile_ranks import oriented_percentile
from golden_vector.features.relative_behavior import compute_relative_behavior_metrics
from golden_vector.features.weekly_returns import build_weekly_return_frame

TOOL_C_OUTPUT_COLUMNS = [
    "ticker",
    "as_of_date",
    "source_run_id",
    "source_tool_a_run_id",
    "snapshot_refresh_run_id",
    "down_beta_core",
    "up_beta_core",
    "asymmetry_ratio_core",
    "downside_volatility_52w",
    "confidence_score",
    "score_eligible",
    "rel_weakness_vs_gold_pct",
    "rel_weakness_vs_gold_n",
    "rel_weakness_vs_gdx_pct",
    "rel_weakness_vs_gdx_n",
    "rel_weakness_vs_gdxj_pct",
    "rel_weakness_vs_gdxj_n",
    "rel_strength_vs_gold_pct",
    "rel_strength_vs_gold_n",
    "rel_strength_vs_gdx_pct",
    "rel_strength_vs_gdx_n",
    "rel_strength_vs_gdxj_pct",
    "rel_strength_vs_gdxj_n",
    "n_weeks_gold",
    "n_weeks_gdx",
    "n_weeks_gdxj",
    "downside_hit_rate_10pct",
    "downside_hit_rate_n",
    "upside_hit_rate_10pct",
    "upside_hit_rate_n",
    "tail_avg_return_worst10pct",
    "tail_avg_return_worst10pct_n",
    "tail_avg_return_worst20pct",
    "tail_avg_return_worst20pct_n",
    "tail_avg_return_best10pct",
    "tail_avg_return_best10pct_n",
    "tail_avg_return_best20pct",
    "tail_avg_return_best20pct_n",
    "tool_c_downside_score",
    "tool_c_downside_rank",
    "tool_c_upside_score",
    "tool_c_upside_rank",
    "tool_c_downside_tags",
    "tool_c_upside_tags",
    "tool_c_downside_explanation",
    "tool_c_upside_explanation",
]

DOWNSIDE_COMPONENTS = [
    "down_beta_core",
    "downside_volatility_52w",
    "rel_weakness_vs_gold_pct",
    "rel_weakness_vs_gdx_pct",
    "rel_weakness_vs_gdxj_pct",
    "downside_hit_rate_10pct",
]
UPSIDE_COMPONENTS = [
    "up_beta_core",
    "rel_strength_vs_gold_pct",
    "rel_strength_vs_gdx_pct",
    "rel_strength_vs_gdxj_pct",
    "upside_hit_rate_10pct",
]
MIN_DOWNSIDE_COMPONENTS = 3
MIN_UPSIDE_COMPONENTS = 3


@dataclass(frozen=True)
class ToolCExecutionInputs:
    """Loaded inputs for Tool C computation."""

    normalized_equity_histories: dict[str, pd.DataFrame]
    gold_history: pd.DataFrame
    benchmark_histories: dict[str, pd.DataFrame]
    tool_a_latest: pd.DataFrame


def compute_tool_c_outputs(
    *,
    inputs: ToolCExecutionInputs,
    config: ToolCConfig,
    source_run_id: str,
) -> pd.DataFrame:
    """Compute Tool C rows from Tool A latest plus weekly return inputs."""

    weekly_returns = build_weekly_return_frame(
        normalized_equity_histories=inputs.normalized_equity_histories,
        gold_history=inputs.gold_history,
        benchmark_histories=inputs.benchmark_histories,
    )
    gold_regimes = build_gold_regime_frame(
        weekly_returns,
        rolling_weeks=config.regime_rolling_weeks,
        min_weeks=config.regime_min_weeks,
        downside_hit_rate_threshold=config.downside_hit_rate_threshold,
        upside_hit_rate_threshold=config.upside_hit_rate_threshold,
    )
    relative_metrics = compute_relative_behavior_metrics(
        weekly_returns=weekly_returns,
        gold_regimes=gold_regimes,
        min_events=config.min_events,
        downside_hit_rate_threshold=config.downside_hit_rate_threshold,
        upside_hit_rate_threshold=config.upside_hit_rate_threshold,
    )
    return build_tool_c_output_frame(
        tool_a_latest=inputs.tool_a_latest,
        relative_metrics=relative_metrics,
        config=config,
        source_run_id=source_run_id,
    )


def build_tool_c_output_frame(
    *,
    tool_a_latest: pd.DataFrame,
    relative_metrics: pd.DataFrame,
    config: ToolCConfig,
    source_run_id: str,
) -> pd.DataFrame:
    """Build the final Tool C output frame from already-computed metrics."""

    base = _prepare_tool_a(tool_a_latest)
    metrics = _prepare_metrics(relative_metrics)
    if base.empty and metrics.empty:
        return pd.DataFrame(columns=TOOL_C_OUTPUT_COLUMNS)
    if base.empty:
        base = pd.DataFrame({"ticker": metrics["ticker"].astype(str)})

    output = base.merge(metrics, how="left", on="ticker")
    if "score_eligible" not in output.columns:
        output["score_eligible"] = True
    output["source_run_id"] = source_run_id
    output["source_tool_a_run_id"] = output.get("source_tool_a_run_id")
    output["snapshot_refresh_run_id"] = output.get("snapshot_refresh_run_id")
    _ensure_columns(output, [*DOWNSIDE_COMPONENTS, *UPSIDE_COMPONENTS])

    _add_component_scores(output, DOWNSIDE_COMPONENTS, score_column="tool_c_downside_score")
    _add_component_scores(output, UPSIDE_COMPONENTS, score_column="tool_c_upside_score")
    _sink_ineligible_rows(output)
    output["tool_c_downside_rank"] = oriented_percentile(
        output["tool_c_downside_score"],
        high_good=True,
    )
    output["tool_c_upside_rank"] = oriented_percentile(
        output["tool_c_upside_score"],
        high_good=True,
    )
    output["tool_c_downside_tags"] = output.apply(
        lambda row: _join_tags(_downside_tags(row, config=config)),
        axis=1,
    )
    output["tool_c_upside_tags"] = output.apply(
        lambda row: _join_tags(_upside_tags(row, config=config)),
        axis=1,
    )
    output["tool_c_downside_explanation"] = output.apply(
        _downside_explanation,
        axis=1,
    )
    output["tool_c_upside_explanation"] = output.apply(
        _upside_explanation,
        axis=1,
    )
    for column in TOOL_C_OUTPUT_COLUMNS:
        if column not in output.columns:
            output[column] = pd.NA
    return output[TOOL_C_OUTPUT_COLUMNS].sort_values(
        ["tool_c_downside_rank", "tool_c_upside_rank", "ticker"],
        ascending=[False, False, True],
        na_position="last",
    ).reset_index(drop=True)


def _prepare_tool_a(tool_a_latest: pd.DataFrame) -> pd.DataFrame:
    if tool_a_latest.empty or "ticker" not in tool_a_latest.columns:
        return pd.DataFrame(columns=["ticker"])
    columns = [
        "ticker",
        "as_of_date",
        "source_run_id",
        "snapshot_refresh_run_id",
        "down_beta_core",
        "up_beta_core",
        "asymmetry_ratio_core",
        "downside_volatility_52w",
        "confidence_score",
        "score_eligible",
    ]
    available = [column for column in columns if column in tool_a_latest.columns]
    result = tool_a_latest[available].copy()
    result["ticker"] = result["ticker"].astype(str).str.upper().str.strip()
    result = result[result["ticker"] != ""].drop_duplicates(subset=["ticker"], keep="last")
    if "source_run_id" in result.columns:
        result = result.rename(columns={"source_run_id": "source_tool_a_run_id"})
    return result.reset_index(drop=True)


def _prepare_metrics(relative_metrics: pd.DataFrame) -> pd.DataFrame:
    if relative_metrics.empty or "ticker" not in relative_metrics.columns:
        return pd.DataFrame(columns=["ticker"])
    result = relative_metrics.copy()
    result["ticker"] = result["ticker"].astype(str).str.upper().str.strip()
    result = result[result["ticker"] != ""].drop_duplicates(subset=["ticker"], keep="last")
    return result.reset_index(drop=True)


def _ensure_columns(output: pd.DataFrame, columns: list[str]) -> None:
    for column in columns:
        if column not in output.columns:
            output[column] = pd.NA


def _add_component_scores(
    output: pd.DataFrame,
    components: Iterable[str],
    *,
    score_column: str,
) -> None:
    percentiles: list[pd.Series] = []
    eligible = score_eligible_mask(output["score_eligible"])
    for component in components:
        values = _numeric(output, component).where(eligible)
        percentiles.append(oriented_percentile(values, high_good=True))
    if not percentiles:
        output[score_column] = pd.NA
        return
    percentile_frame = pd.concat(percentiles, axis=1)
    output[score_column] = percentile_frame.mean(axis=1, skipna=True)


def _sink_ineligible_rows(output: pd.DataFrame) -> None:
    score_eligible = score_eligible_mask(output["score_eligible"])
    downside_count = output[DOWNSIDE_COMPONENTS].apply(
        lambda row: pd.to_numeric(row, errors="coerce").notna().sum(),
        axis=1,
    )
    upside_count = output[UPSIDE_COMPONENTS].apply(
        lambda row: pd.to_numeric(row, errors="coerce").notna().sum(),
        axis=1,
    )
    output["tool_c_downside_score"] = output["tool_c_downside_score"].where(
        score_eligible & downside_count.ge(MIN_DOWNSIDE_COMPONENTS)
    )
    output["tool_c_upside_score"] = output["tool_c_upside_score"].where(
        score_eligible & upside_count.ge(MIN_UPSIDE_COMPONENTS)
    )


def _downside_tags(row: pd.Series, *, config: ToolCConfig) -> list[str]:
    tags: list[str] = []
    if not is_score_eligible(row.get("score_eligible")):
        tags.append("score_ineligible")
    if _optional_float(row.get("confidence_score")) is not None and _optional_float(row.get("confidence_score")) < 0.5:
        tags.append("low_confidence")
    if _optional_float(row.get("down_beta_core")) is not None and _optional_float(row.get("down_beta_core")) >= 1.5:
        tags.append("steep_down_beta")
    if max(
        _optional_float(row.get("rel_weakness_vs_gold_pct")) or 0.0,
        _optional_float(row.get("rel_weakness_vs_gdx_pct")) or 0.0,
        _optional_float(row.get("rel_weakness_vs_gdxj_pct")) or 0.0,
    ) >= 0.6:
        tags.append("persistent_relative_weakness")
    if (_optional_float(row.get("downside_hit_rate_10pct")) or 0.0) >= 0.25:
        tags.append("frequent_deep_drops")
    if _has_thin_history(
        row,
        config=config,
        fields=[
            ("rel_weakness_vs_gold_pct", "rel_weakness_vs_gold_n"),
            ("rel_weakness_vs_gdx_pct", "rel_weakness_vs_gdx_n"),
            ("rel_weakness_vs_gdxj_pct", "rel_weakness_vs_gdxj_n"),
            ("downside_hit_rate_10pct", "downside_hit_rate_n"),
            ("tail_avg_return_worst10pct", "tail_avg_return_worst10pct_n"),
            ("tail_avg_return_worst20pct", "tail_avg_return_worst20pct_n"),
        ],
    ):
        tags.append("thin_history")
    return tags


def _upside_tags(row: pd.Series, *, config: ToolCConfig) -> list[str]:
    tags: list[str] = []
    if not is_score_eligible(row.get("score_eligible")):
        tags.append("score_ineligible")
    if _optional_float(row.get("confidence_score")) is not None and _optional_float(row.get("confidence_score")) < 0.5:
        tags.append("low_confidence")
    if _optional_float(row.get("up_beta_core")) is not None and _optional_float(row.get("up_beta_core")) >= 1.5:
        tags.append("steep_up_beta")
    if max(
        _optional_float(row.get("rel_strength_vs_gold_pct")) or 0.0,
        _optional_float(row.get("rel_strength_vs_gdx_pct")) or 0.0,
        _optional_float(row.get("rel_strength_vs_gdxj_pct")) or 0.0,
    ) >= 0.6:
        tags.append("persistent_relative_strength")
    if (_optional_float(row.get("upside_hit_rate_10pct")) or 0.0) >= 0.25:
        tags.append("frequent_strong_rallies")
    if _has_thin_history(
        row,
        config=config,
        fields=[
            ("rel_strength_vs_gold_pct", "rel_strength_vs_gold_n"),
            ("rel_strength_vs_gdx_pct", "rel_strength_vs_gdx_n"),
            ("rel_strength_vs_gdxj_pct", "rel_strength_vs_gdxj_n"),
            ("upside_hit_rate_10pct", "upside_hit_rate_n"),
            ("tail_avg_return_best10pct", "tail_avg_return_best10pct_n"),
            ("tail_avg_return_best20pct", "tail_avg_return_best20pct_n"),
        ],
    ):
        tags.append("thin_history")
    return tags


def _has_thin_history(
    row: pd.Series,
    *,
    config: ToolCConfig,
    fields: list[tuple[str, str]],
) -> bool:
    for value_column, count_column in fields:
        value = _optional_float(row.get(value_column))
        count = _optional_int(row.get(count_column))
        if value is None and count is not None and count < config.min_events:
            return True
    return False


def _downside_explanation(row: pd.Series) -> str:
    rank = _optional_float(row.get("tool_c_downside_rank"))
    if rank is None:
        return "Not ranked for downside behavior because too few robust inputs are usable."
    down = _optional_float(row.get("down_beta_core"))
    weakness = _optional_float(row.get("rel_weakness_vs_gold_pct"))
    return (
        f"Downside behavior rank {rank:.1f}; down beta "
        f"{_fmt_optional(down)} and gold-down relative weakness {_fmt_pct(weakness)}."
    )


def _upside_explanation(row: pd.Series) -> str:
    rank = _optional_float(row.get("tool_c_upside_rank"))
    if rank is None:
        return "Not ranked for upside behavior because too few robust inputs are usable."
    up = _optional_float(row.get("up_beta_core"))
    strength = _optional_float(row.get("rel_strength_vs_gold_pct"))
    return (
        f"Upside behavior rank {rank:.1f}; up beta "
        f"{_fmt_optional(up)} and gold-up relative strength {_fmt_pct(strength)}."
    )


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([pd.NA] * len(frame.index), index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _optional_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if pd.notna(parsed) else None


def _optional_int(value: object) -> int | None:
    parsed = _optional_float(value)
    return int(parsed) if parsed is not None else None


def _join_tags(tags: list[str]) -> str | None:
    return ";".join(dict.fromkeys(tags)) if tags else None


def _fmt_optional(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"
