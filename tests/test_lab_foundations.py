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


def _patched_vintage_env(tmp_path, monkeypatch, *, sources, freshness_status):
    """Wire record_vintages to fixture sources with a stubbed manifest."""

    from golden_vector.lab import vintages as vintages_module

    monkeypatch.setattr(vintages_module, "_vintage_sources", lambda paths: sources)
    monkeypatch.setattr(
        vintages_module, "load_current_model_state_manifest", lambda paths: {}
    )
    monkeypatch.setattr(
        vintages_module,
        "resolve_current_model_artifact_path",
        lambda paths, name, fallback_path=None: fallback_path,
    )
    monkeypatch.setattr(
        vintages_module,
        "summarize_option_freshness",
        lambda payload: (
            None
            if freshness_status is None
            else {"status": freshness_status, "message": ""}
        ),
    )

    class FakePaths:
        data_dir = tmp_path / "data"

    return vintages_module, FakePaths()


def test_record_vintages_smoke(tmp_path, monkeypatch) -> None:
    artifact = tmp_path / "tool_b_latest.parquet"
    _snapshot_frame().to_parquet(artifact, index=False)
    vintages_module, paths = _patched_vintage_env(
        tmp_path, monkeypatch, sources={"tool_b": artifact}, freshness_status="OK"
    )

    results = vintages_module.record_vintages(
        paths,  # type: ignore[arg-type]
        now=datetime(2026, 6, 12, 10, 0, tzinfo=timezone.utc),
    )
    assert len(results) == 1
    store = tmp_path / "data" / "lab" / "vintages" / "tool_b.parquet"
    assert store.exists()
    stored = pd.read_parquet(store)
    assert set(stored["vintage_date"]) == {"2026-06-12"}
    assert results[0].rows_appended == len(stored)


def test_record_vintages_skips_option_sources_unless_fresh(tmp_path, monkeypatch) -> None:
    """Manifest-rejected option data must never enter the PIT store —
    first-write-wins would make the contamination permanent."""

    artifact = tmp_path / "option_signal_summary_latest.parquet"
    _snapshot_frame().to_parquet(artifact, index=False)
    for status in ("UNAVAILABLE", "CARRIED_FORWARD", None):
        vintages_module, paths = _patched_vintage_env(
            tmp_path,
            monkeypatch,
            sources={"option_signal_summary": artifact},
            freshness_status=status,
        )
        results = vintages_module.record_vintages(
            paths,  # type: ignore[arg-type]
            now=datetime(2026, 6, 12, 10, 0, tzinfo=timezone.utc),
        )
        assert results == [], f"option source recorded under freshness={status}"
        store = tmp_path / "data" / "lab" / "vintages" / "option_signal_summary.parquet"
        assert not store.exists()


def test_record_vintages_isolates_a_corrupt_source(tmp_path, monkeypatch) -> None:
    corrupt = tmp_path / "tool_b_latest.parquet"
    corrupt.write_text("not parquet", encoding="utf-8")
    healthy = tmp_path / "tool_d_latest.parquet"
    _snapshot_frame().to_parquet(healthy, index=False)
    vintages_module, paths = _patched_vintage_env(
        tmp_path,
        monkeypatch,
        sources={"tool_b": corrupt, "tool_d": healthy},
        freshness_status="OK",
    )
    results = vintages_module.record_vintages(
        paths,  # type: ignore[arg-type]
        now=datetime(2026, 6, 12, 10, 0, tzinfo=timezone.utc),
    )
    assert [item.source for item in results] == ["tool_d"]
    assert (tmp_path / "data" / "lab" / "vintages" / "tool_d.parquet").exists()


def test_load_ledger_quarantines_torn_final_line_only(tmp_path) -> None:
    import json

    from golden_vector.lab.ledger import ledger_path, load_ledger, register_variant

    register_variant(lab_dir=tmp_path, signal_id="beta_gap", config={"w": 1})
    path = ledger_path(tmp_path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"variant_hash": "abc", "signal_id"')  # torn append
    records = load_ledger(tmp_path)
    assert len(records) == 1  # healthy record survives, torn line quarantined
    assert path.with_suffix(".jsonl.torn").exists()
    # The torn line is REMOVED from the ledger so it cannot swallow a
    # future append.
    assert '"signal_id"\n' not in path.read_text(encoding="utf-8")

    # A malformed NON-final line is real corruption and must fail loud.
    healthy_line = path.read_text(encoding="utf-8").splitlines()[0]
    path.write_text('{"broken"\n' + healthy_line + "\n", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_ledger(tmp_path)


def test_register_after_torn_line_never_merges(tmp_path) -> None:
    """A torn final line (crash mid-append, no trailing newline) must not
    merge with the next registration — that would silently swallow the new
    record and undercount n_trials."""

    from golden_vector.lab.ledger import (
        ledger_path,
        load_ledger,
        n_trials,
        register_variant,
    )

    register_variant(lab_dir=tmp_path, signal_id="a", config={"w": 1})
    path = ledger_path(tmp_path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"torn')  # no trailing newline
    record = register_variant(lab_dir=tmp_path, signal_id="b", config={"w": 2})
    records = load_ledger(tmp_path)
    assert record.variant_hash in {entry.variant_hash for entry in records}
    assert n_trials(tmp_path) == 2  # both registrations counted
