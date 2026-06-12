"""Scorecard publisher gates: pre-registration, leak gate, accrual, provenance.

The expensive end-to-end publish is exercised by running
``python -m golden_vector.lab.scorecard``; these tests pin the GATES cheaply
(no full backtest), which is where the publish discipline lives.
"""

from __future__ import annotations

import json

import pytest

from golden_vector.lab import scorecard as sc


def test_registered_hash_refuses_unregistered_signal(tmp_path):
    """HIGH-2: a signal with no ledger entry cannot publish."""

    from golden_vector.lab.ledger import register_variant

    with pytest.raises(ValueError, match="not registered"):
        sc._registered_hash(tmp_path, "validation_e1b")
    rec = register_variant(lab_dir=tmp_path, signal_id="validation_e1b", config={"v": 1})
    assert sc._registered_hash(tmp_path, "validation_e1b") == rec.variant_hash


def test_backtest_signals_are_actually_registered_in_the_repo_ledger():
    """Every backtest signal the publisher will stamp must be in the live
    ledger — the publish-time pre-registration check."""

    from golden_vector.app.paths import ProjectPaths
    from golden_vector.lab.ledger import n_trials
    from golden_vector.lab.vintages import lab_dir

    lab = lab_dir(ProjectPaths.discover())
    for sid in sc.BACKTEST_SIGNAL_IDS:
        assert n_trials(lab, signal_id=sid) > 0, f"{sid} not registered"


def test_fold_ic_autocorr():
    class F:
        def __init__(self, ic):
            self.ic = ic

    # perfectly alternating -> negative lag-1 autocorr
    folds = [F(x) for x in [1.0, -1.0, 1.0, -1.0, 1.0, -1.0]]
    ac = sc._fold_ic_autocorr(folds)
    assert ac is not None and ac < 0
    assert sc._fold_ic_autocorr([F(0.1), F(0.2)]) is None  # <3 -> None


def test_accrual_rows_are_accruing_and_carry_pinned_fields(tmp_path):
    """E4: forward-only signals render as ACCRUING with the pinned field
    names and a first-verdict date (never a premature verdict)."""

    class FakePaths:
        data_dir = tmp_path

    # an empty vintage dir -> 0 accrued weeks, still ACCRUING rows
    (tmp_path / "lab" / "vintages").mkdir(parents=True)
    rows = sc._accrual_rows(FakePaths())  # type: ignore[arg-type]
    assert len(rows) == len(sc.ACCRUAL_SIGNALS)
    for row in rows:
        assert row["kind"] == "accruing"
        assert row["verdict"].startswith("ACCRUING")
        assert row["mean_ic"] is None  # never a number before data accrues


def test_scorecard_columns_are_stable():
    """The /scorecard page renders these columns; pin the contract."""

    expected = {
        "signal_id", "claim", "verdict", "kind", "n_folds", "mean_ic", "nw_t",
        "share_folds_directional", "tercile_spread_mean", "tercile_spread_t",
        "median_ceiling", "fold_ic_autocorr", "baseline_lines", "gate_results",
        "variant_hash", "caveat",
    }

    class V:
        signal_id = "x"; claim = "c"; verdict = "SUPPORTED"; n_folds = 10
        mean_ic = 0.3; nw_t = 4.0; share_folds_directional = 0.8
        tercile_spread_mean = 0.3; tercile_spread_t = 3.0; median_ceiling = 0.4
        baseline_lines: list = []; gate_results: dict = {}

    row = sc._verdict_row(V(), [], kind="backtest", variant_hash="abc")
    assert set(row) == expected
    assert json.loads(row["baseline_lines"]) == []
