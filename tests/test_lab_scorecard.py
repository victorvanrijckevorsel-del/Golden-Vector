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


# --------------------------------------------- /scorecard page (render-only)


def test_scorecard_page_renders_verdicts_and_caveats(tmp_path):
    import pandas as pd

    from golden_vector.serve.overview_scorecard import _render_scorecard_page
    from golden_vector.serve.scorecard_data import load_scorecard_data
    from golden_vector.lab.scorecard import (
        SCORECARD_META_FILENAME,
        SCORECARD_SCHEMA_VERSION,
        SCORECARD_TABLE_FILENAME,
    )

    lab = tmp_path / "lab"
    lab.mkdir()
    rows = [
        {"signal_id": "validation_e1b", "claim": "Tool A predicts forward beta",
         "verdict": "SUPPORTED (exploratory - survivor-only universe)", "kind": "backtest",
         "n_folds": 44, "mean_ic": 0.48, "nw_t": 18.3, "share_folds_directional": 1.0,
         "tercile_spread_mean": 1.11, "tercile_spread_t": 11.3, "median_ceiling": 0.28,
         "fold_ic_autocorr": 0.2, "baseline_lines": json.dumps([]), "gate_results": json.dumps({}),
         "variant_hash": "abc", "caveat": "survivor-only"},
        {"signal_id": "tool_b_health", "claim": "Tool B forward alpha",
         "verdict": "ACCRUING (first verdict expected ~2031-04)",
         "kind": "accruing", "n_folds": 0, "mean_ic": None, "nw_t": None,
         "share_folds_directional": None, "tercile_spread_mean": None, "tercile_spread_t": None,
         "median_ceiling": None, "fold_ic_autocorr": None, "baseline_lines": json.dumps([]),
         "gate_results": json.dumps({}), "variant_hash": None, "caveat": "Forward-only"},
    ]
    pd.DataFrame(rows).to_parquet(lab / SCORECARD_TABLE_FILENAME, index=False)
    (lab / SCORECARD_META_FILENAME).write_text(json.dumps({
        "schema_version": SCORECARD_SCHEMA_VERSION,
        "built_at_utc": "2026-06-12T17:33:00+00:00",
        "leak_canary": {"honest_mean_ic": 0.48, "contaminated_mean_ic": 1.0, "contrast": 0.52},
        "caveats": ["SUPPORTED, not VALIDATED: survivor-only universe."],
    }))

    class FakePaths:
        data_dir = tmp_path

    data = load_scorecard_data(FakePaths())  # type: ignore[arg-type]
    assert data.available and len(data.backtest_rows) == 1 and len(data.accruing_rows) == 1
    html = _render_scorecard_page(data)
    assert "Evidence Scorecard" in html
    assert "verdict-supported" in html
    assert "verdict-accruing" in html
    assert "Tool A predicts forward beta" in html
    assert "survivor-only universe" in html
    assert "Leak check passed" in html
    assert "evidence, not proof" in html
    assert ">Scorecard</a>" in html  # nav tab


def test_scorecard_page_formats_nan_diagnostics_as_blank(tmp_path):
    import pandas as pd

    from golden_vector.lab.scorecard import (
        SCORECARD_META_FILENAME,
        SCORECARD_SCHEMA_VERSION,
        SCORECARD_TABLE_FILENAME,
    )
    from golden_vector.serve.overview_scorecard import _render_scorecard_page
    from golden_vector.serve.scorecard_data import load_scorecard_data

    lab = tmp_path / "lab"
    lab.mkdir()
    row = {
        "signal_id": "validation_e1a",
        "claim": "Tool A rank is stable out of sample",
        "verdict": "SUPPORTED (exploratory - survivor-only universe)",
        "kind": "backtest",
        "n_folds": 43,
        "mean_ic": 0.61,
        "nw_t": float("nan"),
        "share_folds_directional": 0.98,
        "tercile_spread_mean": float("nan"),
        "tercile_spread_t": float("nan"),
        "median_ceiling": float("nan"),
        "fold_ic_autocorr": float("nan"),
        "baseline_lines": json.dumps([]),
        "gate_results": json.dumps({}),
        "variant_hash": "abc",
        "caveat": "survivor-only",
    }
    pd.DataFrame([row]).to_parquet(lab / SCORECARD_TABLE_FILENAME, index=False)
    (lab / SCORECARD_META_FILENAME).write_text(json.dumps({
        "schema_version": SCORECARD_SCHEMA_VERSION,
        "built_at_utc": "2026-06-12T17:33:00+00:00",
    }))

    class FakePaths:
        data_dir = tmp_path

    html = _render_scorecard_page(load_scorecard_data(FakePaths()))  # type: ignore[arg-type]
    assert "t nan" not in html.lower()
    assert "spread nan" not in html.lower()
    assert "consistency nan" not in html.lower()
    assert "t -" in html


def test_scorecard_loader_flags_stale_schema(tmp_path):
    import pandas as pd

    from golden_vector.lab.scorecard import (
        SCORECARD_META_FILENAME,
        SCORECARD_TABLE_FILENAME,
    )
    from golden_vector.serve.scorecard_data import load_scorecard_data

    lab = tmp_path / "lab"
    lab.mkdir()
    rows = [{
        "signal_id": "validation_e1b",
        "claim": "Tool A predicts forward beta",
        "verdict": "SUPPORTED",
        "kind": "backtest",
        "n_folds": 1,
        "mean_ic": 0.1,
        "nw_t": 1.0,
        "share_folds_directional": 1.0,
        "tercile_spread_mean": 0.1,
        "tercile_spread_t": 1.0,
        "median_ceiling": 0.2,
        "fold_ic_autocorr": None,
        "baseline_lines": json.dumps([]),
        "gate_results": json.dumps({}),
        "variant_hash": "abc",
        "caveat": "",
    }]
    pd.DataFrame(rows).to_parquet(lab / SCORECARD_TABLE_FILENAME, index=False)
    (lab / SCORECARD_META_FILENAME).write_text(json.dumps({"schema_version": 0}))

    class FakePaths:
        data_dir = tmp_path

    data = load_scorecard_data(FakePaths())  # type: ignore[arg-type]
    assert not data.available
    assert data.error_status == "STALE"


def test_scorecard_page_surfaces_legacy_schema_compatibility(tmp_path):
    import pandas as pd

    from golden_vector.lab.scorecard import (
        SCORECARD_META_FILENAME,
        SCORECARD_TABLE_FILENAME,
    )
    from golden_vector.serve.overview_scorecard import _render_scorecard_page
    from golden_vector.serve.scorecard_data import load_scorecard_data

    lab = tmp_path / "lab"
    lab.mkdir()
    rows = [{
        "signal_id": "validation_e1b",
        "claim": "Tool A predicts forward beta",
        "verdict": "SUPPORTED",
        "kind": "backtest",
        "n_folds": 1,
        "mean_ic": 0.1,
        "nw_t": 1.0,
        "share_folds_directional": 1.0,
        "tercile_spread_mean": 0.1,
        "tercile_spread_t": 1.0,
        "median_ceiling": 0.2,
        "fold_ic_autocorr": None,
        "baseline_lines": json.dumps([]),
        "gate_results": json.dumps({}),
        "variant_hash": "abc",
        "caveat": "",
    }]
    pd.DataFrame(rows).to_parquet(lab / SCORECARD_TABLE_FILENAME, index=False)
    (lab / SCORECARD_META_FILENAME).write_text(json.dumps({
        "built_at_utc": "2026-06-12T17:33:00+00:00",
    }))

    class FakePaths:
        data_dir = tmp_path

    data = load_scorecard_data(FakePaths())  # type: ignore[arg-type]
    assert data.available
    assert data.meta["legacy_schema_assumed"] is True
    html = _render_scorecard_page(data)
    assert "predates schema metadata" in html


def test_scorecard_serve_layer_has_no_analytics():
    """Render-only: the scorecard serve files must not compute verdicts/stats."""

    from pathlib import Path as P

    for module in ("scorecard_data.py", "overview_scorecard.py"):
        src = P(f"golden_vector/serve/{module}").read_text(encoding="utf-8")
        code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
        for forbidden in (".mean(", ".std(", ".rank(", "newey_west", "spearman",
                          "_validity_experiment", "run_e1", "run_e3", ".quantile("):
            assert forbidden not in code, f"{module}: {forbidden}"
