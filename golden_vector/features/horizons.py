"""Horizon parsing and date-resolution helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

import pandas as pd

from golden_vector.contracts.config_models import (
    CustomHorizonValidation,
    HorizonsConfig,
)

HorizonUnit = Literal["D", "M", "Y"]
HorizonMode = Literal["core", "custom"]
HORIZON_ID_PATTERN = re.compile(r"^(?P<value>\d+)(?P<unit>[DMY])$")


@dataclass(frozen=True)
class ParsedHorizon:
    horizon_id: str
    value: int
    unit: HorizonUnit
    mode: HorizonMode


def build_core_horizons(horizons_config: HorizonsConfig) -> list[ParsedHorizon]:
    core_horizon_ids = {horizon_id.upper() for horizon_id in horizons_config.core_horizons}
    return [
        parse_horizon_id(horizon_id, core_horizon_ids=core_horizon_ids)
        for horizon_id in horizons_config.core_horizons
    ]


def parse_horizon_id(
    horizon_id: str,
    *,
    core_horizon_ids: set[str] | None = None,
    custom_validation: CustomHorizonValidation | None = None,
) -> ParsedHorizon:
    normalized_horizon_id = horizon_id.strip().upper()
    match = HORIZON_ID_PATTERN.match(normalized_horizon_id)
    if not match:
        raise ValueError(f"Invalid horizon id: {horizon_id}")

    value = int(match.group("value"))
    unit = match.group("unit")
    mode: HorizonMode = (
        "core"
        if core_horizon_ids and normalized_horizon_id in core_horizon_ids
        else "custom"
    )

    if mode == "custom" and custom_validation is not None:
        _validate_custom_horizon(
            value=value,
            unit=unit,
            custom_validation=custom_validation,
        )

    return ParsedHorizon(
        horizon_id=normalized_horizon_id,
        value=value,
        unit=unit,  # type: ignore[arg-type]
        mode=mode,
    )


def parse_requested_horizons(
    raw_value: str,
    horizons_config: HorizonsConfig,
) -> list[ParsedHorizon]:
    raw_horizon_ids = [part.strip() for part in raw_value.split(",") if part.strip()]
    if not raw_horizon_ids:
        raise ValueError("At least one horizon id is required.")

    normalized_horizon_ids = [horizon_id.upper() for horizon_id in raw_horizon_ids]
    if len(set(normalized_horizon_ids)) != len(normalized_horizon_ids):
        raise ValueError("Requested horizons must be unique.")

    core_horizon_ids = {horizon_id.upper() for horizon_id in horizons_config.core_horizons}
    return [
        parse_horizon_id(
            horizon_id,
            core_horizon_ids=core_horizon_ids,
            custom_validation=horizons_config.custom_validation,
        )
        for horizon_id in raw_horizon_ids
    ]


def resolve_horizon_start_date(
    available_dates: pd.Series | pd.Index | list[date],
    *,
    as_of_date: date,
    horizon: ParsedHorizon,
) -> date | None:
    dates = _normalize_dates(available_dates)
    if dates.empty:
        return None

    as_of_timestamp = pd.Timestamp(as_of_date)
    if as_of_timestamp not in set(dates):
        return None

    if horizon.unit == "D":
        position = dates.get_loc(as_of_timestamp)
        start_position = position - horizon.value
        if start_position < 0:
            return None
        return dates[start_position].date()

    offset = (
        pd.DateOffset(months=horizon.value)
        if horizon.unit == "M"
        else pd.DateOffset(years=horizon.value)
    )
    target_date = as_of_timestamp - offset
    candidates = dates[dates <= target_date]
    if len(candidates) == 0:
        return None
    return candidates[-1].date()


def _normalize_dates(
    available_dates: pd.Series | pd.Index | list[date],
) -> pd.DatetimeIndex:
    if isinstance(available_dates, pd.Index):
        dates = pd.to_datetime(available_dates)
    else:
        dates = pd.to_datetime(pd.Series(available_dates))
    normalized = pd.DatetimeIndex(dates).dropna().unique().sort_values()
    return normalized


def _validate_custom_horizon(
    *,
    value: int,
    unit: str,
    custom_validation: CustomHorizonValidation,
) -> None:
    if unit not in custom_validation.allowed_units:
        raise ValueError(
            "Custom horizon unit must be one of: "
            + ", ".join(custom_validation.allowed_units)
        )
    if value < custom_validation.min_value or value > custom_validation.max_value:
        raise ValueError(
            f"Custom horizon value must be between {custom_validation.min_value} and "
            f"{custom_validation.max_value}."
        )
