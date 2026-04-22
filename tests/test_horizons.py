from datetime import date

import pytest

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.features.horizons import (
    build_core_horizons,
    parse_horizon_id,
    parse_requested_horizons,
    resolve_horizon_start_date,
)


def test_build_core_horizons_uses_configured_order():
    app_config = load_app_config(ProjectPaths.discover()).app

    horizons = build_core_horizons(app_config.horizons)

    assert horizons[0].horizon_id == "5D"
    assert horizons[0].mode == "core"
    assert horizons[-1].horizon_id == "3Y"


def test_parse_horizon_id_marks_custom_horizons():
    parsed = parse_horizon_id("45D", core_horizon_ids={"5D", "10D"})

    assert parsed.horizon_id == "45D"
    assert parsed.value == 45
    assert parsed.unit == "D"
    assert parsed.mode == "custom"


def test_parse_horizon_id_rejects_invalid_values():
    with pytest.raises(ValueError, match="Invalid horizon id"):
        parse_horizon_id("banana")


def test_parse_requested_horizons_keeps_order_and_validates_customs():
    app_config = load_app_config(ProjectPaths.discover()).app

    parsed = parse_requested_horizons("5D,45D,3M", app_config.horizons)

    assert [item.horizon_id for item in parsed] == ["5D", "45D", "3M"]
    assert [item.mode for item in parsed] == ["core", "custom", "core"]


def test_parse_requested_horizons_rejects_duplicates():
    app_config = load_app_config(ProjectPaths.discover()).app

    with pytest.raises(ValueError, match="unique"):
        parse_requested_horizons("5D,5d", app_config.horizons)


def test_resolve_horizon_start_date_uses_trading_day_offsets():
    available_dates = [
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
    ]
    horizon = parse_horizon_id("5D", core_horizon_ids={"5D"})

    start_date = resolve_horizon_start_date(
        available_dates,
        as_of_date=date(2026, 1, 8),
        horizon=horizon,
    )

    assert start_date == date(2026, 1, 1)


def test_resolve_horizon_start_date_uses_prior_trading_day_for_calendar_offsets():
    available_dates = [
        date(2026, 1, 30),
        date(2026, 2, 2),
        date(2026, 2, 27),
        date(2026, 3, 2),
        date(2026, 3, 31),
    ]
    horizon = parse_horizon_id("1M", core_horizon_ids={"1M"})

    start_date = resolve_horizon_start_date(
        available_dates,
        as_of_date=date(2026, 3, 31),
        horizon=horizon,
    )

    assert start_date == date(2026, 2, 27)
