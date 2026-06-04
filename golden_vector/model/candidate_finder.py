"""Pure scoring engine for the Candidate Finder."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, Literal

import pandas as pd

from golden_vector.features.percentile_ranks import oriented_percentile

CriterionDirection = Literal["high_good", "low_good"]
VALID_DIRECTIONS = frozenset({"high_good", "low_good"})

TOOL_A_SCORE_ELIGIBLE_FIELDS = frozenset(
    {
        "down_beta_core",
        "up_beta_core",
        "structural_delta_core",
        "downside_volatility_52w",
    }
)


@dataclass(frozen=True)
class CriterionDefinition:
    id: str
    label: str
    source_field: str
    group: str
    default_direction: CriterionDirection
    unit: str = ""


@dataclass(frozen=True)
class CriterionSelection:
    id: str
    direction: CriterionDirection | None = None
    weight: float | None = None


@dataclass(frozen=True)
class ResolvedCriterion:
    id: str
    label: str
    source_field: str
    group: str
    direction: CriterionDirection
    weight: float
    unit: str = ""


@dataclass(frozen=True)
class CriterionTopEntry:
    ticker: str
    criterion_id: str
    raw_value: float
    percentile: float
    rank: int


@dataclass(frozen=True)
class CandidateScore:
    ticker: str
    score: float | None
    rank: int | None
    rank_eligible: bool
    present_criteria_count: int
    selected_criteria_count: int
    criteria_fraction: float
    top_n_tally: int
    percentiles: dict[str, float | None]
    raw_values: dict[str, float | None]
    missing_criteria: tuple[str, ...]
    source_score_eligible: bool


@dataclass(frozen=True)
class CandidateFinderResult:
    rows: tuple[CandidateScore, ...]
    top_lists: dict[str, tuple[CriterionTopEntry, ...]]
    selected_criteria: tuple[ResolvedCriterion, ...]
    warnings: tuple[str, ...] = ()


def rank_candidates(
    frame: pd.DataFrame,
    *,
    criteria: list[Any],
    selections: list[CriterionSelection],
    top_n: int = 10,
    min_criteria_fraction: float = 0.67,
    ticker_column: str = "ticker",
) -> CandidateFinderResult:
    """Rank a pre-filtered candidate frame by weighted oriented percentiles."""

    warnings: list[str] = []
    if top_n <= 0:
        raise ValueError("top_n must be positive")
    if min_criteria_fraction <= 0 or min_criteria_fraction > 1:
        raise ValueError("min_criteria_fraction must be greater than 0 and at most 1")

    registry = {
        _get_text(criterion, "id"): _criterion_definition(criterion)
        for criterion in criteria
    }
    selected = _resolve_selections(
        registry=registry,
        selections=selections,
        warnings=warnings,
    )
    if not selected:
        warnings.append("Pick at least one criterion.")
        return CandidateFinderResult(
            rows=(),
            top_lists={},
            selected_criteria=(),
            warnings=tuple(warnings),
        )

    data = _prepare_frame(frame, ticker_column=ticker_column)
    if data.empty:
        return CandidateFinderResult(
            rows=(),
            top_lists={criterion.id: () for criterion in selected},
            selected_criteria=tuple(selected),
            warnings=tuple(warnings),
        )

    percentiles: dict[str, pd.Series] = {}
    raw_values: dict[str, pd.Series] = {}
    top_lists: dict[str, tuple[CriterionTopEntry, ...]] = {}
    top_sets: dict[str, set[str]] = {}

    for criterion in selected:
        values = _criterion_values(data, criterion)
        raw_values[criterion.id] = values
        percentile = oriented_percentile(
            values,
            high_good=criterion.direction == "high_good",
        )
        percentiles[criterion.id] = percentile
        top_entries = _top_entries(
            criterion=criterion,
            values=values,
            percentiles=percentile,
            top_n=top_n,
        )
        top_lists[criterion.id] = tuple(top_entries)
        top_sets[criterion.id] = {entry.ticker for entry in top_entries}

    rows = _score_rows(
        data=data,
        selected=selected,
        raw_values=raw_values,
        percentiles=percentiles,
        top_sets=top_sets,
        min_criteria_fraction=min_criteria_fraction,
    )
    ranked_rows = _assign_ranks(_sort_rows(rows))
    return CandidateFinderResult(
        rows=tuple(ranked_rows),
        top_lists=top_lists,
        selected_criteria=tuple(selected),
        warnings=tuple(warnings),
    )


def _resolve_selections(
    *,
    registry: dict[str, CriterionDefinition],
    selections: list[CriterionSelection],
    warnings: list[str],
) -> list[ResolvedCriterion]:
    resolved: list[ResolvedCriterion] = []
    seen: set[str] = set()
    for selection in selections:
        selection_id = str(selection.id).strip()
        if selection_id in seen:
            warnings.append(f"Duplicate criterion ignored: {selection_id}")
            continue
        criterion = registry.get(selection_id)
        if criterion is None:
            warnings.append(f"Unknown criterion ignored: {selection.id}")
            continue
        seen.add(selection_id)
        direction = _selection_direction(
            selection.direction,
            default_direction=criterion.default_direction,
            criterion_id=criterion.id,
            warnings=warnings,
        )
        weight = _selection_weight(
            selection.weight,
            criterion_id=criterion.id,
            warnings=warnings,
        )
        resolved.append(
            ResolvedCriterion(
                id=criterion.id,
                label=criterion.label,
                source_field=criterion.source_field,
                group=criterion.group,
                direction=direction,
                weight=max(0.0, weight),
                unit=criterion.unit,
            )
        )
    if resolved and all(criterion.weight <= 0 for criterion in resolved):
        resolved = [replace(criterion, weight=1.0) for criterion in resolved]
    elif resolved:
        disabled_ids = [criterion.id for criterion in resolved if criterion.weight <= 0]
        if disabled_ids:
            warnings.append(
                "Zero-weight criteria disabled: " + ", ".join(disabled_ids) + "."
            )
            resolved = [
                criterion for criterion in resolved if criterion.weight > 0
            ]
    return resolved


def _selection_direction(
    value: object,
    *,
    default_direction: CriterionDirection,
    criterion_id: str,
    warnings: list[str],
) -> CriterionDirection:
    if value is None:
        return default_direction
    normalized = str(value).strip()
    if normalized in VALID_DIRECTIONS:
        return normalized  # type: ignore[return-value]
    warnings.append(
        f"Invalid direction for {criterion_id}; defaulted to {default_direction}."
    )
    return default_direction


def _selection_weight(
    value: object,
    *,
    criterion_id: str,
    warnings: list[str],
) -> float:
    if value is None:
        return 1.0
    try:
        weight = float(value)
    except (TypeError, ValueError):
        warnings.append(f"Invalid weight for {criterion_id}; defaulted to 1.0.")
        return 1.0
    if not math.isfinite(weight):
        warnings.append(f"Invalid weight for {criterion_id}; defaulted to 1.0.")
        return 1.0
    if weight < 0:
        warnings.append(f"Negative weight for {criterion_id}; treated as 0.")
        return 0.0
    return weight


def _prepare_frame(frame: pd.DataFrame, *, ticker_column: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=[ticker_column]).set_index(ticker_column, drop=False)
    data = frame.copy()
    if ticker_column not in data.columns:
        data[ticker_column] = data.index.astype(str)
    data[ticker_column] = data[ticker_column].astype(str).str.strip().str.upper()
    data = data[data[ticker_column] != ""].copy()
    if data.empty:
        return data.set_index(ticker_column, drop=False)
    data = data.drop_duplicates(subset=[ticker_column], keep="last")
    return data.set_index(ticker_column, drop=False)


def _criterion_values(data: pd.DataFrame, criterion: ResolvedCriterion) -> pd.Series:
    if criterion.source_field not in data.columns:
        return pd.Series([pd.NA] * len(data.index), index=data.index, dtype="Float64")
    values = pd.to_numeric(data[criterion.source_field], errors="coerce")
    if criterion.source_field in TOOL_A_SCORE_ELIGIBLE_FIELDS and "score_eligible" in data.columns:
        score_eligible = data["score_eligible"].map(_truthy_score_eligible)
        values = values.mask(~score_eligible)
    return values


def _top_entries(
    *,
    criterion: ResolvedCriterion,
    values: pd.Series,
    percentiles: pd.Series,
    top_n: int,
) -> list[CriterionTopEntry]:
    combined = pd.DataFrame(
        {
            "ticker": values.index.astype(str),
            "raw_value": values,
            "percentile": percentiles,
        }
    ).dropna(subset=["raw_value", "percentile"]).reset_index(drop=True)
    if combined.empty:
        return []
    combined = combined.sort_values(
        ["percentile", "ticker"],
        ascending=[False, True],
        kind="mergesort",
    ).head(top_n)
    return [
        CriterionTopEntry(
            ticker=str(row.ticker),
            criterion_id=criterion.id,
            raw_value=float(row.raw_value),
            percentile=float(row.percentile),
            rank=index + 1,
        )
        for index, row in enumerate(combined.itertuples(index=False))
    ]


def _score_rows(
    *,
    data: pd.DataFrame,
    selected: list[ResolvedCriterion],
    raw_values: dict[str, pd.Series],
    percentiles: dict[str, pd.Series],
    top_sets: dict[str, set[str]],
    min_criteria_fraction: float,
) -> list[CandidateScore]:
    rows: list[CandidateScore] = []
    selected_count = len(selected)
    for ticker in data.index.astype(str):
        present: list[ResolvedCriterion] = []
        row_percentiles: dict[str, float | None] = {}
        row_values: dict[str, float | None] = {}
        missing: list[str] = []
        weighted_total = 0.0
        present_weight = 0.0

        for criterion in selected:
            percentile = _optional_float(percentiles[criterion.id].get(ticker))
            raw_value = _optional_float(raw_values[criterion.id].get(ticker))
            row_percentiles[criterion.id] = percentile
            row_values[criterion.id] = raw_value
            if percentile is None:
                missing.append(criterion.id)
                continue
            present.append(criterion)
            weighted_total += criterion.weight * percentile
            present_weight += criterion.weight

        score = weighted_total / present_weight if present_weight > 0 else None
        criteria_fraction = len(present) / selected_count
        rows.append(
            CandidateScore(
                ticker=ticker,
                score=score,
                rank=None,
                rank_eligible=_is_rank_eligible(
                    present_count=len(present),
                    selected_count=selected_count,
                    min_criteria_fraction=min_criteria_fraction,
                ),
                present_criteria_count=len(present),
                selected_criteria_count=selected_count,
                criteria_fraction=criteria_fraction,
                top_n_tally=sum(ticker in top_sets[criterion.id] for criterion in selected),
                percentiles=row_percentiles,
                raw_values=row_values,
                missing_criteria=tuple(missing),
                source_score_eligible=_row_score_eligible(data, ticker),
            )
        )
    return rows


def _sort_rows(rows: list[CandidateScore]) -> list[CandidateScore]:
    return sorted(
        rows,
        key=lambda row: (
            not row.rank_eligible,
            row.score is None,
            -(row.score or 0.0),
            -row.top_n_tally,
            row.ticker,
        ),
    )


def _assign_ranks(rows: list[CandidateScore]) -> list[CandidateScore]:
    ranked: list[CandidateScore] = []
    next_rank = 1
    for row in rows:
        if row.rank_eligible and row.score is not None:
            ranked.append(replace(row, rank=next_rank))
            next_rank += 1
        else:
            ranked.append(row)
    return ranked


def _is_rank_eligible(
    *,
    present_count: int,
    selected_count: int,
    min_criteria_fraction: float,
) -> bool:
    if selected_count <= 0:
        return False
    return round(present_count / selected_count, 2) >= min_criteria_fraction


def _criterion_definition(criterion: Any) -> CriterionDefinition:
    return CriterionDefinition(
        id=_get_text(criterion, "id"),
        label=_get_text(criterion, "label"),
        source_field=_get_text(criterion, "source_field"),
        group=_get_text(criterion, "group"),
        default_direction=_get_text(criterion, "default_direction"),  # type: ignore[arg-type]
        unit=_get_text(criterion, "unit", default=""),
    )


def _get_text(value: Any, field: str, *, default: str | None = None) -> str:
    if isinstance(value, dict):
        raw = value.get(field, default)
    else:
        raw = getattr(value, field, default)
    if raw is None:
        if default is not None:
            return default
        raise ValueError(f"Missing candidate finder criterion field: {field}")
    return str(raw).strip()


def _row_score_eligible(data: pd.DataFrame, ticker: str) -> bool:
    if "score_eligible" not in data.columns:
        return True
    return _truthy_score_eligible(data.at[ticker, "score_eligible"])


def _truthy_score_eligible(value: object) -> bool:
    if value is None or pd.isna(value):
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() not in {"false", "0", "no", "n"}


def _optional_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
