"""Lab M0 foundations: benchmark USD fallback, variant ledger, vintage recorder."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from golden_vector.features.weekly_returns import _price_basis
from golden_vector.lab.ledger import (
    load_ledger,
    n_trials,
    register_variant,
    require_registered,
    variant_hash,
)
from golden_vector.lab.vintages import (
    VINTAGE_COLUMNS,
    _append_vintage,
    _melt_snapshot,
)


def _benchmark_frame(currency: str = "USD") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-05-29", "2026-06-05"]),
            "ticker": ["GDX", "GDX"],
            "currency": [currency, currency],
            "close_local": [40.0, 42.0],
            "adj_close_local": [39.5, 41.5],
        }
    )


def test_price_basis_falls_back_to_local_for_usd_benchmark() -> None:
    basis = _price_basis(_benchmark_frame())
    assert basis.notna().all()
    assert float(basis.iloc[0]) == 39.5


def test_price_basis_does_not_fall_back_for_non_usd() -> None:
    basis = _price_basis(_benchmark_frame(currency="CAD"))
    assert basis.isna().all()


def test_price_basis_prefers_usd_columns_when_present() -> None:
    frame = _benchmark_frame()
    frame["adj_close_usd"] = [100.0, 101.0]
    basis = _price_basis(frame)
    assert float(basis.iloc[0]) == 100.0


def test_register_variant_is_idempotent_and_counts_trials(tmp_path) -> None:
    config = {"window_weeks": 26, "shrinkage": "james_stein"}
    first = register_variant(lab_dir=tmp_path, signal_id="beta_gap", config=config)
    second = register_variant(lab_dir=tmp_path, signal_id="beta_gap", config=config)
    assert first.variant_hash == second.variant_hash == variant_hash("beta_gap", config)
    assert len(load_ledger(tmp_path)) == 1
    register_variant(lab_dir=tmp_path, signal_id="beta_gap", config={"window_weeks": 52})
    register_variant(lab_dir=tmp_path, signal_id="other", config={})
    assert n_trials(tmp_path) == 3
    assert n_trials(tmp_path, signal_id="beta_gap") == 2


def test_require_registered_blocks_unregistered_variant(tmp_path) -> None:
    with pytest.raises(ValueError, match="not in the ledger"):
        require_registered(lab_dir=tmp_path, signal_id="beta_gap", config={"w": 1})
    register_variant(lab_dir=tmp_path, signal_id="beta_gap", config={"w": 1})
    digest = require_registered(lab_dir=tmp_path, signal_id="beta_gap", config={"w": 1})
    assert digest == variant_hash("beta_gap", {"w": 1})


def _snapshot_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ["AEM", "NEM"],
            "score": [1.5, float("nan")],
            "status": ["OK", "STALE"],
            "flag": [True, False],
        }
    )


def test_melt_snapshot_long_format_skips_nulls() -> None:
    melted = _melt_snapshot(
        _snapshot_frame(),
        source="tool_b",
        vintage_date="2026-06-12",
        recorded_at_utc="2026-06-12T10:00:00+00:00",
    )
    assert list(melted.columns) == VINTAGE_COLUMNS
    aem = melted[melted["ticker"] == "AEM"].set_index("field")
    assert aem.loc["score", "value_num"] == 1.5
    assert aem.loc["status", "value_text"] == "OK"
    assert aem.loc["flag", "value_num"] == 1.0
    nem_fields = set(melted[melted["ticker"] == "NEM"]["field"])
    assert "score" not in nem_fields  # NaN dropped, not stored


def test_append_vintage_first_write_wins(tmp_path) -> None:
    store = tmp_path / "tool_b.parquet"
    rows = _melt_snapshot(
        _snapshot_frame(),
        source="tool_b",
        vintage_date="2026-06-12",
        recorded_at_utc="2026-06-12T10:00:00+00:00",
    )
    first = _append_vintage(store, rows, source="tool_b")
    assert first.rows_appended == len(rows)

    changed = _snapshot_frame()
    changed["score"] = [9.9, 9.9]
    rerun = _melt_snapshot(
        changed,
        source="tool_b",
        vintage_date="2026-06-12",
        recorded_at_utc="2026-06-12T18:00:00+00:00",
    )
    second = _append_vintage(store, rerun, source="tool_b")
    stored = pd.read_parquet(store)
    aem_score = stored[(stored["ticker"] == "AEM") & (stored["field"] == "score")]
    assert len(aem_score) == 1
    assert float(aem_score["value_num"].iloc[0]) == 1.5  # first write wins
    assert second.rows_skipped_existing > 0

    next_day = _melt_snapshot(
        changed,
        source="tool_b",
        vintage_date="2026-06-19",
        recorded_at_utc="2026-06-19T10:00:00+00:00",
    )
    third = _append_vintage(store, next_day, source="tool_b")
    assert third.rows_appended == len(next_day)  # new vintage date appends


def test_record_vintages_smoke(tmp_path, monkeypatch) -> None:
    from golden_vector.lab import vintages as vintages_module

    artifact = tmp_path / "tool_b_latest.parquet"
    _snapshot_frame().to_parquet(artifact, index=False)

    monkeypatch.setattr(
        vintages_module,
        "_vintage_sources",
        lambda paths: {"tool_b": artifact},
    )

    class FakePaths:
        data_dir = tmp_path / "data"

    results = vintages_module.record_vintages(
        FakePaths(),  # type: ignore[arg-type]
        now=datetime(2026, 6, 12, 10, 0, tzinfo=timezone.utc),
    )
    assert len(results) == 1
    store = tmp_path / "data" / "lab" / "vintages" / "tool_b.parquet"
    assert store.exists()
    stored = pd.read_parquet(store)
    assert set(stored["vintage_date"]) == {"2026-06-12"}
    assert results[0].rows_appended == len(stored)
