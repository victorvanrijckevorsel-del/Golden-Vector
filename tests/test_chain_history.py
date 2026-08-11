"""Daily option-chain history gates (plan §6.1–§6.3)."""

from __future__ import annotations

import pandas as pd
import pytest

from golden_vector.contracts.config_models import OptionHistoryQualityConfig
from golden_vector.contracts.option_artifacts import (
    CHAIN_HISTORY_COLUMNS,
    CHAIN_HISTORY_SCHEMA_VERSION,
)
from golden_vector.hedge.chain_history import (
    CAPTURE_QUALITY_COMPLETE,
    ROW_STATUS_OBSERVED,
    build_chain_history_daily,
)

QUALITY = OptionHistoryQualityConfig()


def capture(
    *,
    as_of_date: str,
    run_id: str,
    total_open_interest: int,
    n_contracts: int = 400,
    n_expirations: int = 12,
    **overrides,
) -> dict:
    row = {
        "ticker": "AEM",
        "as_of_date": as_of_date,
        "run_id": run_id,
        "total_open_interest": total_open_interest,
        "put_oi_total": total_open_interest // 2,
        "call_oi_total": total_open_interest - total_open_interest // 2,
        "put_oi_otm": total_open_interest // 4,
        "call_oi_otm": total_open_interest // 4,
        "total_volume": 5000,
        "put_volume": 2000,
        "call_volume": 3000,
        "put_call_oi_ratio_total": 1.0,
        "put_call_oi_ratio_otm": 1.0,
        "n_contracts": n_contracts,
        "n_expirations": n_expirations,
    }
    row.update(overrides)
    return row


def build(frames, previous=None, published_run_id="20260811T120000Z-refresh-aaaaaaaa"):
    return build_chain_history_daily(
        features_frames={
            ticker: pd.DataFrame(rows) for ticker, rows in frames.items()
        },
        previous_history=previous,
        quality=QUALITY,
        published_run_id=published_run_id,
    )


def test_same_day_partial_capture_loses_to_the_complete_one():
    """354079-style partial vs 534406-style complete on the same day."""

    result = build(
        {
            "AEM": [
                capture(
                    as_of_date="2026-08-10",
                    run_id="20260810T140000Z-refresh-00000001",
                    total_open_interest=354079,
                    n_contracts=210,
                    n_expirations=6,
                ),
                capture(
                    as_of_date="2026-08-10",
                    run_id="20260810T193000Z-refresh-00000002",
                    total_open_interest=534406,
                ),
            ]
        }
    )
    assert len(result.index) == 1
    row = result.iloc[0]
    assert row["total_open_interest"] == 534406
    assert row["capture_run_id"] == "20260810T193000Z-refresh-00000002"
    assert row["row_status"] == ROW_STATUS_OBSERVED
    assert bool(row["oi_split_backfilled"]) is False
    assert row["schema_version"] == CHAIN_HISTORY_SCHEMA_VERSION
    assert list(result.columns) == list(CHAIN_HISTORY_COLUMNS)


def test_same_day_tie_breaks_on_the_latest_run_id():
    result = build(
        {
            "AEM": [
                capture(
                    as_of_date="2026-08-10",
                    run_id="20260810T140000Z-refresh-00000001",
                    total_open_interest=500000,
                ),
                capture(
                    as_of_date="2026-08-10",
                    run_id="20260810T193000Z-refresh-00000002",
                    total_open_interest=500000,
                ),
            ]
        }
    )
    assert result.iloc[0]["capture_run_id"] == "20260810T193000Z-refresh-00000002"


def _healthy_previous(dates: list[str]) -> pd.DataFrame:
    rows = []
    for index, day in enumerate(dates):
        row = capture(
            as_of_date=day,
            run_id=f"2026{index:04d}T120000Z-refresh-0000000{index}",
            total_open_interest=500000,
        )
        row.update(
            {
                "capture_quality": CAPTURE_QUALITY_COMPLETE,
                "row_status": ROW_STATUS_OBSERVED,
                "oi_split_backfilled": False,
                "capture_run_id": row.pop("run_id"),
                "published_run_id": "20260801T120000Z-refresh-old00000",
                "schema_version": CHAIN_HISTORY_SCHEMA_VERSION,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def test_lone_day_below_the_trailing_floor_is_flagged_not_crowned():
    previous = _healthy_previous(["2026-08-0%d" % day for day in range(1, 8)])
    result = build(
        {
            "AEM": [
                capture(
                    as_of_date="2026-08-10",
                    run_id="20260810T140000Z-refresh-00000009",
                    total_open_interest=50_000,  # << 0.5 x trailing median
                    n_contracts=20,
                    n_expirations=1,
                )
            ]
        },
        previous=previous,
    )
    today = result[result["as_of_date"] == "2026-08-10"].iloc[0]
    assert today["capture_quality"].startswith("PARTIAL:")
    for field in ("total_open_interest", "n_contracts", "n_expirations"):
        assert f"below_trailing_floor:{field}" in today["capture_quality"]
    # Control: a healthy capture on the same trailing window stays COMPLETE.
    healthy = build(
        {
            "AEM": [
                capture(
                    as_of_date="2026-08-10",
                    run_id="20260810T140000Z-refresh-00000009",
                    total_open_interest=520_000,
                )
            ]
        },
        previous=previous,
    )
    row = healthy[healthy["as_of_date"] == "2026-08-10"].iloc[0]
    assert row["capture_quality"] == CAPTURE_QUALITY_COMPLETE


def test_field_gate_nas_a_negative_oi_but_keeps_the_row():
    result = build(
        {
            "AEM": [
                capture(
                    as_of_date="2026-08-10",
                    run_id="20260810T140000Z-refresh-00000009",
                    total_open_interest=500_000,
                    put_oi_total=-5,
                    put_call_oi_ratio_total=-1.0,
                )
            ]
        }
    )
    assert len(result.index) == 1
    row = result.iloc[0]
    assert row["put_oi_total"] is None or pd.isna(row["put_oi_total"])
    assert row["put_call_oi_ratio_total"] is None or pd.isna(row["put_call_oi_ratio_total"])
    # The row survives, with the reason recorded and the good fields intact.
    assert row["total_open_interest"] == 500_000
    assert "negative:put_oi_total" in row["capture_quality"]
    assert "negative:put_call_oi_ratio_total" in row["capture_quality"]


def test_no_shrink_raises_and_a_control_merge_passes():
    previous = _healthy_previous(["2026-08-03", "2026-08-04"])
    # Control: merging today's capture keeps both prior rows.
    merged = build(
        {"AEM": [capture(as_of_date="2026-08-05", run_id="r3", total_open_interest=500_000)]},
        previous=previous,
    )
    assert set(merged["as_of_date"]) == {"2026-08-03", "2026-08-04", "2026-08-05"}

    # A previous history for a ticker absent from today's features must still
    # survive: dropping it is the failure the guard exists for.
    other = previous.assign(ticker="NEM")
    combined = pd.concat([previous, other], ignore_index=True)
    kept = build(
        {"AEM": [capture(as_of_date="2026-08-05", run_id="r3", total_open_interest=500_000)]},
        previous=combined,
    )
    assert set(kept.loc[kept["ticker"] == "NEM", "as_of_date"]) == {
        "2026-08-03",
        "2026-08-04",
    }

    # Direct guard check: a merge that loses a prior key raises.
    from golden_vector.hedge import chain_history

    def _losing_merge(*, previous, observed):
        return observed.copy()

    original = chain_history._merge_forward
    chain_history._merge_forward = _losing_merge
    try:
        with pytest.raises(ValueError, match="Refusing to publish option chain history"):
            build(
                {
                    "AEM": [
                        capture(
                            as_of_date="2026-08-05",
                            run_id="r3",
                            total_open_interest=500_000,
                        )
                    ]
                },
                previous=previous,
            )
    finally:
        chain_history._merge_forward = original


def test_merge_keeps_legacy_rows_intact():
    previous = _healthy_previous(["2026-08-03", "2026-08-04"])
    merged = build(
        {"AEM": [capture(as_of_date="2026-08-05", run_id="r3", total_open_interest=500_000)]},
        previous=previous,
        published_run_id="20260811T120000Z-refresh-bbbbbbbb",
    )
    carried = merged[merged["as_of_date"] == "2026-08-03"].iloc[0]
    original = previous[previous["as_of_date"] == "2026-08-03"].iloc[0]
    # Every legacy field except the current-publisher stamp is byte-identical;
    # columns the legacy schema predates (per-side counts) must be explicit
    # unknowns on carried rows, never invented values.
    for column in CHAIN_HISTORY_COLUMNS:
        if column == "published_run_id":
            continue
        if column not in original.index:
            assert pd.isna(carried[column]), column
            continue
        assert carried[column] == original[column], column
    assert carried["published_run_id"] == "20260811T120000Z-refresh-bbbbbbbb"
    assert carried["capture_run_id"] == original["capture_run_id"]


def test_empty_inputs_return_the_declared_schema():
    result = build({}, previous=None)
    assert result.empty
    assert list(result.columns) == list(CHAIN_HISTORY_COLUMNS)


def _previous_with_side_counts(dates: list[str]) -> pd.DataFrame:
    """Trailing history that DOES carry the per-side contract counts."""

    previous = _healthy_previous(dates)
    previous["put_n_contracts"] = 200
    previous["call_n_contracts"] = 200
    return previous


def test_collapsed_put_side_is_flagged_while_a_control_capture_passes():
    previous = _previous_with_side_counts(["2026-08-0%d" % day for day in range(1, 8)])
    collapsed = build(
        {
            "AEM": [
                capture(
                    as_of_date="2026-08-10",
                    run_id="20260810T140000Z-refresh-00000009",
                    total_open_interest=500_000,
                    put_n_contracts=5,  # << 0.5 x trailing median of 200
                    call_n_contracts=200,
                )
            ]
        },
        previous=previous,
    )
    today = collapsed[collapsed["as_of_date"] == "2026-08-10"].iloc[0]
    assert "below_trailing_floor:put_n_contracts" in today["capture_quality"]
    assert "below_trailing_floor:call_n_contracts" not in today["capture_quality"]

    control = build(
        {
            "AEM": [
                capture(
                    as_of_date="2026-08-10",
                    run_id="20260810T140000Z-refresh-00000009",
                    total_open_interest=500_000,
                    put_n_contracts=198,
                    call_n_contracts=202,
                )
            ]
        },
        previous=previous,
    )
    row = control[control["as_of_date"] == "2026-08-10"].iloc[0]
    assert row["capture_quality"] == CAPTURE_QUALITY_COMPLETE
    # The optional counts never leak into the contracted schema.
    assert list(control.columns) == list(CHAIN_HISTORY_COLUMNS)


def test_old_rows_without_side_counts_do_not_trip_the_new_floors():
    # Trailing history predates the per-side counts entirely...
    previous = _healthy_previous(["2026-08-0%d" % day for day in range(1, 8)])
    result = build(
        {
            "AEM": [
                capture(
                    as_of_date="2026-08-10",
                    run_id="20260810T140000Z-refresh-00000009",
                    total_open_interest=500_000,
                    put_n_contracts=1,
                    call_n_contracts=1,
                )
            ]
        },
        previous=previous,
    )
    assert (
        result[result["as_of_date"] == "2026-08-10"].iloc[0]["capture_quality"]
        == CAPTURE_QUALITY_COMPLETE
    )

    # ...and the mirror case: trailing history has them, today's capture does not.
    today_missing = build(
        {
            "AEM": [
                capture(
                    as_of_date="2026-08-10",
                    run_id="20260810T140000Z-refresh-00000009",
                    total_open_interest=500_000,
                )
            ]
        },
        previous=_previous_with_side_counts(
            ["2026-08-0%d" % day for day in range(1, 8)]
        ),
    )
    assert (
        today_missing[today_missing["as_of_date"] == "2026-08-10"].iloc[0][
            "capture_quality"
        ]
        == CAPTURE_QUALITY_COMPLETE
    )
