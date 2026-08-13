"""Stage-level tests for the ``ticker-page`` orchestrator (plan §5.3, §5.4, §5.5).

The producers themselves are covered by ``test_ticker_page_producers.py``; this
file proves the STAGE contract: identity stamping, atomic-ish publication under
fault injection, alignment, the standalone abort, the skip-tool-b gate, and
pruning.
"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from golden_vector.app.config import load_app_config
from golden_vector.app.model_state import (
    REQUIRED_ARTIFACTS,
    TICKER_PAGE_ARTIFACT_NAMES,
    write_current_model_state_manifest,
)
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.app.run_pruning import prune_runs
from golden_vector.app.ticker_page_stage import (
    TickerPageGenerationMismatchError,
    assert_tool_generation_aligned,
    load_ticker_page_stage_inputs,
    run_ticker_page_stage,
)
from golden_vector.app import ticker_page_state
from golden_vector.app.ticker_page_state import (
    STATUS_CORRUPT,
    STATUS_MISSING,
    STATUS_OK,
    STATUS_PENDING_FIRST_PUBLISH,
    STATUS_STALE,
    load_gold_response,
    load_performance_series,
    load_research_series,
    load_score_percentiles,
)
from golden_vector.contracts.ticker_page import (
    TICKER_PAGE_PROVENANCE_COLUMNS,
    empty_artifact_frame,
)
from golden_vector.contracts.tool_d import (
    TOOL_D_OUTPUT_COLUMNS,
    TOOL_D_SCHEMA_VERSION,
)
from golden_vector.ingestion import persist_ticker_page as persist_module
from golden_vector.ingestion.persist_ticker_page import (
    LINEARITY_DIAGNOSTICS_FILE_NAME,
    stamp_ticker_page_provenance,
)
from golden_vector.screening.manual_data import (
    bootstrap_manual_screening_data,
    load_manual_screening_data,
)
from golden_vector.screening.manual_store import upsert_company_input
from tests.helpers import build_test_paths, tool_b_output_row

TICKERS = ["AEM", "AGI"]
SPOT_GOLD = 3500.0
FOUNDATION_RUN_ID = "20260601T120000Z-refresh"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _only_active_tickers(app_config, *tickers: str):
    targets = {ticker.upper() for ticker in tickers}
    new_tickers = [
        ticker.model_copy(update={"active": ticker.ticker in targets})
        for ticker in app_config.universe.tickers
    ]
    return app_config.model_copy(
        update={"universe": app_config.universe.model_copy(update={"tickers": new_tickers})}
    )


def _manual_payload(ticker: str, *, aisc: float) -> dict[str, object]:
    return {
        "ticker": ticker,
        "production_oz": 1_000_000,
        "aisc_usd_per_oz": aisc,
        "cash_cost_usd_per_oz": 900,
        "royalty_rate": 0.03,
        "sustaining_capex_musd": 150,
        "da_musd": 100,
        "interest_expense_musd": 40,
        "tax_rate": 0.30,
        "reserve_life_years": 12,
        "net_debt_musd": 500,
        "ebitda_ltm_musd": 900,
    }


def _market_snapshots() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "snapshot_date": date(2026, 6, 1),
                "share_price_usd": 60.0,
                "market_cap_usd": 6_000_000_000.0,
                "shares_outstanding": 100_000_000.0,
                "normalization_status": "OK",
            }
            for ticker in TICKERS
        ]
    )


def _daily_dates() -> pd.DatetimeIndex:
    # ~6 years of business days so the 1Y/3Y/5Y horizons all have data.
    return pd.bdate_range("2020-06-01", "2026-06-01")


def _gold_history() -> pd.DataFrame:
    dates = _daily_dates()
    values = pd.Series(range(len(dates)), dtype="float64") * 0.4 + 2000.0
    frame = pd.DataFrame(
        {
            "date": dates,
            "adj_close_usd": values.to_numpy(),
            "close_usd": values.to_numpy(),
        }
    )
    # Pin the last close so spot gold is deterministic.
    frame.loc[frame.index[-1], ["adj_close_usd", "close_usd"]] = SPOT_GOLD
    return frame


def _equity_history(ticker: str, *, scale: float) -> pd.DataFrame:
    dates = _daily_dates()
    values = (pd.Series(range(len(dates)), dtype="float64") * 0.01 + 10.0) * scale
    return pd.DataFrame(
        {
            "ticker": ticker,
            "date": dates,
            "return_basis_usd": values.to_numpy(),
            "adj_close_usd": values.to_numpy(),
            "normalization_status": "OK",
        }
    )


def _tool_b_frame() -> pd.DataFrame:
    """A full-schema Tool B frame: the yahoo materialization needs every column."""

    return pd.DataFrame(
        [
            tool_b_output_row(
                ticker,
                as_of_date=date(2026, 6, 1),
                snapshot_refresh_run_id=FOUNDATION_RUN_ID,
                fundamental_check_rank=index + 1,
            )
            for index, ticker in enumerate(TICKERS)
        ]
    )


def _tool_frame(column: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                column: float(index + 1),
                "as_of_date": "2026-06-01",
                "snapshot_refresh_run_id": FOUNDATION_RUN_ID,
            }
            for index, ticker in enumerate(TICKERS)
        ]
    )


@pytest.fixture()
def stage_env(tmp_path):
    paths = build_test_paths(tmp_path)
    loaded = load_app_config(ProjectPaths.discover())
    app_config = _only_active_tickers(loaded.app, *TICKERS)
    bootstrap_manual_screening_data(paths, tickers=TICKERS)
    for index, ticker in enumerate(TICKERS):
        upsert_company_input(
            paths, ticker=ticker, values=_manual_payload(ticker, aisc=1300.0 + 100 * index)
        )
    manual_data = load_manual_screening_data(paths, tickers=TICKERS)
    return {
        "paths": paths,
        "config_hash": loaded.config_hash,
        "kwargs": {
            "paths": paths,
            "app_config": app_config,
            "parent_refresh_id": FOUNDATION_RUN_ID,
            "snapshot_refresh_run_id": FOUNDATION_RUN_ID,
            "config_hash": loaded.config_hash,
            "upstream_run_ids": {"tool_a": "run-a", "tool_b": "run-b"},
            "manual_data": manual_data,
            "normalized_market_snapshots": _market_snapshots(),
            "official_fundamentals": None,
            "gold_history": _gold_history(),
            "normalized_equity_histories": {
                ticker: _equity_history(ticker, scale=1.0 + index)
                for index, ticker in enumerate(TICKERS)
            },
            "tool_a_latest": _tool_frame("up_beta"),
            "tool_b_latest": _tool_b_frame(),
            "tool_c_latest": _tool_frame("tool_c_score"),
            "tool_d_latest": _tool_frame("tool_d_quality_score"),
            "structural_window_metrics": pd.DataFrame(),
            "benchmark_histories": {},
            "benchmark_series_run_ids": {},
            "snapshot_as_of_date": "2026-06-01",
        },
    }


def test_tool_d_source_completeness_uses_configured_tool_b_universe(stage_env):
    """A ticker absent from both artifacts must not escape the v4 gate."""

    row = {column: None for column in TOOL_D_OUTPUT_COLUMNS}
    rows = []
    for source in ("our", "yahoo"):
        source_row = dict(row)
        source_row.update(
            {
                "ticker": TICKERS[0],
                "finance_source": source,
                "tool_d_schema_version": TOOL_D_SCHEMA_VERSION,
                "as_of_date": "2026-06-01",
                "gold_price_used": SPOT_GOLD,
                "spot_gold_usd": SPOT_GOLD,
                "resilience_data_status": "OK",
            }
        )
        rows.append(source_row)
    frame = pd.DataFrame(rows, columns=TOOL_D_OUTPUT_COLUMNS)
    configured = [
        ticker.ticker
        for ticker in stage_env["kwargs"]["app_config"].universe.tickers
        if ticker.active and ticker.tool_b_enabled
    ]

    assert set(configured) == set(TICKERS)
    paths = stage_env["paths"]
    tool_frames = {
        paths.latest_tool_a_snapshot_parquet_path: pd.DataFrame(
            [{"ticker": TICKERS[0]}]
        ),
        paths.latest_tool_b_snapshot_parquet_path: pd.DataFrame(
            [{"ticker": TICKERS[0]}]
        ),
        paths.latest_tool_c_snapshot_parquet_path: pd.DataFrame(
            [{"ticker": TICKERS[0]}]
        ),
        paths.latest_tool_d_spot_snapshot_parquet_path: frame,
    }
    for path, tool_frame in tool_frames.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        tool_frame.to_parquet(path, index=False)

    with pytest.raises(ValueError, match=rf"missing expected .*\({TICKERS[1]}, our\)"):
        load_ticker_page_stage_inputs(
            paths=paths,
            app_config=stage_env["kwargs"]["app_config"],
            config_hash=stage_env["config_hash"],
            foundation_snapshot=None,
            use_model_state=False,
            manual_data=stage_env["kwargs"]["manual_data"],
            official_fundamentals=None,
        )


def _run_stage(stage_env, *, command: str = "ticker-page"):
    paths = stage_env["paths"]
    run_context = RunContext.start(
        paths=paths,
        command=command,
        parameters={},
        config_hash=stage_env["config_hash"],
    )
    summary = run_ticker_page_stage(run_context=run_context, **stage_env["kwargs"])
    return run_context, summary


def _write_foundation_manifest(paths, *, refresh_run_id: str = FOUNDATION_RUN_ID) -> None:
    paths.latest_foundation_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    paths.latest_foundation_manifest_path.write_text(
        json.dumps(
            {
                "refresh_run_id": refresh_run_id,
                "foundation_status": "PASS",
                "snapshot_as_of_date": "2026-06-01",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# 1. end-to-end
# ---------------------------------------------------------------------------


def test_stage_builds_persists_and_stamps_all_five_artifacts(stage_env):
    paths = stage_env["paths"]
    run_context, summary = _run_stage(stage_env)

    for alias in (
        paths.latest_ticker_page_gold_response_path,
        paths.latest_ticker_page_percentiles_path,
        paths.latest_ticker_page_performance_path,
        paths.latest_ticker_page_research_series_path,
        paths.latest_ticker_page_fx_attribution_path,
        paths.latest_ticker_page_downside_context_path,
    ):
        assert alias.exists(), alias

    diagnostics = run_context.run_dir / persist_module.LINEARITY_DIAGNOSTICS_FILE_NAME
    assert diagnostics.exists()

    # Per-substep self-reporting (soul.md #4): seconds + rows for every substep.
    assert set(summary["timings"]) == {
        "gold_response",
        "percentiles",
        "performance",
        "research_series",
        "fx_attribution",
        "downside_context",
        "persist",
    }
    for entry in summary["timings"].values():
        assert entry["duration_seconds"] >= 0
    assert summary["rows"]["gold_response"] > 0
    assert summary["rows"]["percentiles"] > 0
    assert summary["rows"]["performance"] > 0
    assert summary["timings"]["persist"]["rows_persisted"] == sum(
        summary["rows"][name]
        for name in (
            "gold_response",
            "percentiles",
            "performance",
            "research_series",
            "fx_attribution",
            "downside_context",
        )
    )

    # Provenance is stamped by the persistence layer on every artifact.
    for alias in (
        paths.latest_ticker_page_gold_response_path,
        paths.latest_ticker_page_percentiles_path,
        paths.latest_ticker_page_performance_path,
        paths.latest_ticker_page_research_series_path,
    ):
        frame = pd.read_parquet(alias)
        for column in TICKER_PAGE_PROVENANCE_COLUMNS:
            assert column in frame.columns
        if frame.empty:
            continue
        assert set(frame["snapshot_refresh_run_id"]) == {FOUNDATION_RUN_ID}
        assert set(frame["parent_refresh_id"]) == {FOUNDATION_RUN_ID}
        assert set(frame["source_run_id"]) == {run_context.run_id}
        assert set(frame["config_hash"]) == {stage_env["config_hash"]}


def test_loaders_report_pending_then_ok_once_a_refresh_publishes(stage_env):
    paths = stage_env["paths"]
    _run_stage(stage_env)

    # A standalone build is non-authoritative: the artifacts exist but no
    # manifest names them yet.
    for loader in (
        load_gold_response,
        load_score_percentiles,
        load_performance_series,
        load_research_series,
    ):
        state = loader(paths)
        assert state.status == STATUS_PENDING_FIRST_PUBLISH
        assert "awaiting first refresh publication" in (state.reason or "")

    _write_foundation_manifest(paths)
    write_current_model_state_manifest(
        paths=paths,
        config_hash=stage_env["config_hash"],
        parent_refresh_id=FOUNDATION_RUN_ID,
        stage_timings={},
    )
    for loader in (
        load_gold_response,
        load_score_percentiles,
        load_performance_series,
        load_research_series,
    ):
        state = loader(paths)
        assert state.status == STATUS_OK, (loader.__name__, state.reason)
        assert not state.frame.empty


def test_ticker_page_artifacts_are_required_for_a_complete_model_state():
    for name in TICKER_PAGE_ARTIFACT_NAMES:
        assert name in REQUIRED_ARTIFACTS


# ---------------------------------------------------------------------------
# 2. fault injection (§5.3)
# ---------------------------------------------------------------------------


def test_interrupted_publish_leaves_the_other_previous_aliases_and_manifest_intact(
    stage_env, monkeypatch
):
    paths = stage_env["paths"]
    _run_stage(stage_env)
    _write_foundation_manifest(paths)
    write_current_model_state_manifest(
        paths=paths,
        config_hash=stage_env["config_hash"],
        parent_refresh_id=FOUNDATION_RUN_ID,
        stage_timings={},
    )
    manifest_before = paths.latest_model_state_manifest_path.read_bytes()
    untouched_before = {
        alias: alias.read_bytes()
        for alias in (
            paths.latest_ticker_page_percentiles_path,
            paths.latest_ticker_page_performance_path,
            paths.latest_ticker_page_research_series_path,
        )
    }

    real_write = persist_module.write_parquet_atomic
    calls: list[str] = []

    def failing_write(frame, path):
        calls.append(path.name)
        # gold_response writes three files (immutable, run-stamped latest, alias);
        # fail immediately after the FIRST artifact is fully written.
        if path.name.startswith("percentiles_"):
            raise OSError("injected fault after the first artifact")
        return real_write(frame, path)

    monkeypatch.setattr(persist_module, "write_parquet_atomic", failing_write)
    with pytest.raises(OSError, match="injected fault"):
        _run_stage(stage_env)

    assert any(name.startswith("gold_response_") for name in calls)
    for alias, before in untouched_before.items():
        assert alias.read_bytes() == before, f"{alias.name} was modified by the failed publish"
    # The stage never writes the manifest; only a refresh does.
    assert paths.latest_model_state_manifest_path.read_bytes() == manifest_before

    # The previous complete generation still serves every artifact.
    for loader in (
        load_gold_response,
        load_score_percentiles,
        load_performance_series,
        load_research_series,
    ):
        assert loader(paths).status == STATUS_OK


def test_loaders_report_missing_when_nothing_was_ever_built(stage_env):
    paths = stage_env["paths"]
    assert load_gold_response(paths).status == STATUS_MISSING
    assert load_score_percentiles(paths).status == STATUS_MISSING


# ---------------------------------------------------------------------------
# 3. alignment
# ---------------------------------------------------------------------------


def test_mismatched_snapshot_run_id_is_flagged_by_health_and_read_as_stale(stage_env):
    paths = stage_env["paths"]
    _run_stage(stage_env)

    # Re-stamp ONLY percentiles with a different generation; the healthy control
    # (gold_response) must keep reading OK.
    for path in sorted(paths.output_ticker_page_dir.glob("percentiles_*.parquet")):
        frame = pd.read_parquet(path)
        frame["snapshot_refresh_run_id"] = "20260101T000000Z-other"
        frame.to_parquet(path, index=False)

    _write_foundation_manifest(paths)
    manifest = write_current_model_state_manifest(
        paths=paths,
        config_hash=stage_env["config_hash"],
        parent_refresh_id=FOUNDATION_RUN_ID,
        stage_timings={},
    )

    warnings = manifest["alignment"]["ticker_page_artifact_warnings"]
    assert any(warning.startswith("ticker_page_percentiles") for warning in warnings)
    assert manifest["alignment"]["status"] == "WARN"

    stale = load_score_percentiles(paths)
    assert stale.status == STATUS_STALE
    assert "misaligned" in (stale.reason or "")
    assert stale.frame.empty
    assert load_gold_response(paths).status == STATUS_OK


def test_sha_mismatch_against_the_manifest_reads_stale(stage_env):
    paths = stage_env["paths"]
    _run_stage(stage_env)
    _write_foundation_manifest(paths)
    write_current_model_state_manifest(
        paths=paths,
        config_hash=stage_env["config_hash"],
        parent_refresh_id=FOUNDATION_RUN_ID,
        stage_timings={},
    )
    state = load_gold_response(paths)
    assert state.status == STATUS_OK

    manifest = json.loads(paths.latest_model_state_manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["ticker_page_gold_response"]["sha256"] = "0" * 64
    paths.latest_model_state_manifest_path.write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    stale = load_gold_response(paths)
    assert stale.status == STATUS_STALE
    assert "sha256" in (stale.reason or "")


# ---------------------------------------------------------------------------
# 4. standalone abort on a mixed tool generation
# ---------------------------------------------------------------------------


def _manifest_with_tool_ids(ids: dict[str, str]) -> dict:
    return {
        "artifacts": {
            name: {"snapshot_refresh_run_ids": [run_id]}
            for name, run_id in ids.items()
        }
    }


def test_standalone_accepts_an_aligned_generation():
    aligned = _manifest_with_tool_ids(
        {name: FOUNDATION_RUN_ID for name in ("tool_a", "tool_b", "tool_c", "tool_d")}
    )
    assert assert_tool_generation_aligned(aligned) == FOUNDATION_RUN_ID


def test_standalone_aborts_on_mixed_tool_generations(tmp_path):
    paths = build_test_paths(tmp_path)
    mixed = _manifest_with_tool_ids(
        {
            "tool_a": FOUNDATION_RUN_ID,
            "tool_b": FOUNDATION_RUN_ID,
            "tool_c": "20260101T000000Z-other",
            "tool_d": FOUNDATION_RUN_ID,
        }
    )
    with pytest.raises(TickerPageGenerationMismatchError, match="not aligned"):
        assert_tool_generation_aligned(mixed)
    assert not list(paths.output_ticker_page_dir.glob("*.parquet"))


def test_standalone_aborts_when_no_manifest_exists():
    with pytest.raises(TickerPageGenerationMismatchError, match="No current model-state manifest"):
        assert_tool_generation_aligned(None)


def test_standalone_cli_returns_2_and_writes_nothing_on_a_mixed_generation(
    tmp_path, monkeypatch, capsys
):
    from golden_vector import cli

    paths = build_test_paths(tmp_path)
    monkeypatch.setattr(
        cli,
        "load_current_model_state_manifest",
        lambda _paths: _manifest_with_tool_ids(
            {
                "tool_a": FOUNDATION_RUN_ID,
                "tool_b": "20260101T000000Z-other",
                "tool_c": FOUNDATION_RUN_ID,
                "tool_d": FOUNDATION_RUN_ID,
            }
        ),
    )
    assert cli.run_ticker_page(paths) == 2
    assert "ticker-page aborted" in capsys.readouterr().out
    assert not list(paths.output_ticker_page_dir.glob("*.parquet"))


# ---------------------------------------------------------------------------
# 5. --skip-tool-b gate
# ---------------------------------------------------------------------------


def test_refresh_skip_tool_b_does_not_run_the_ticker_page_stage(tmp_path, monkeypatch, capsys):
    from golden_vector import cli

    paths = build_test_paths(tmp_path)
    calls: list[str] = []

    monkeypatch.setattr(cli, "run_foundation", lambda _p, **_k: 0)
    monkeypatch.setattr(cli, "run_tool_a", lambda _p: 0)
    monkeypatch.setattr(
        cli, "run_ticker_page", lambda *_a, **_k: calls.append("ticker-page") or 0
    )
    monkeypatch.setattr(cli, "_run_portfolio_refresh_step", lambda _p, **_k: 0)

    assert cli.run_refresh(paths, gold_price_override=None, skip_tool_b=True) == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "tool-b/tool-c/tool-d SKIPPED" in out
    assert "ticker-page" not in out.lower().split("skipped")[0]


# ---------------------------------------------------------------------------
# 6. pruning
# ---------------------------------------------------------------------------


def test_pruning_covers_ticker_page_outputs_and_keeps_the_current_generation(stage_env):
    paths = stage_env["paths"]
    _run_stage(stage_env)
    _write_foundation_manifest(paths)
    write_current_model_state_manifest(
        paths=paths,
        config_hash=stage_env["config_hash"],
        parent_refresh_id=FOUNDATION_RUN_ID,
        stage_timings={},
    )
    assert ticker_page_state.load_gold_response(paths).status == STATUS_OK

    # An older generation's run-stamped files are candidates.
    stale_file = paths.output_ticker_page_dir / "gold_response_output_20200101T000000Z-old.parquet"
    stale_latest = paths.output_ticker_page_dir / "gold_response_latest_20200101T000000Z-old.parquet"
    for path in (stale_file, stale_latest):
        pd.DataFrame({"ticker": ["AEM"]}).to_parquet(path, index=False)

    report = prune_runs(paths, apply=False)
    candidate_names = {
        candidate.path.name
        for candidate in report.candidates
        if candidate.kind == "artifact"
    }
    assert stale_file.name in candidate_names
    assert stale_latest.name in candidate_names
    # The current generation's immutable is never a candidate.
    current_immutables = [
        path.name
        for path in paths.output_ticker_page_dir.glob("gold_response_latest_*.parquet")
        if "20200101" not in path.name
    ]
    assert current_immutables
    for name in current_immutables:
        assert name not in candidate_names


# ---------------------------------------------------------------------------
# 7. two-pass atomic publish (adversarial-review regression gates)
# ---------------------------------------------------------------------------


_ALL_ALIAS_ATTRS = (
    "latest_ticker_page_gold_response_path",
    "latest_ticker_page_percentiles_path",
    "latest_ticker_page_performance_path",
    "latest_ticker_page_research_series_path",
)


def _published_generation(stage_env):
    """Run the stage once and publish model state; return the four alias bytes."""

    paths = stage_env["paths"]
    _run_stage(stage_env)
    _write_foundation_manifest(paths)
    write_current_model_state_manifest(
        paths=paths,
        config_hash=stage_env["config_hash"],
        parent_refresh_id=FOUNDATION_RUN_ID,
        stage_timings={},
    )
    return {
        attr: getattr(paths, attr).read_bytes() for attr in _ALL_ALIAS_ATTRS
    }


def _assert_previous_generation_intact(paths, before, manifest_before):
    for attr, expected in before.items():
        actual = getattr(paths, attr).read_bytes()
        assert actual == expected, f"{attr} alias was flipped by a failed publish"
    assert paths.latest_model_state_manifest_path.read_bytes() == manifest_before
    for loader in (
        load_gold_response,
        load_score_percentiles,
        load_performance_series,
        load_research_series,
    ):
        assert loader(paths).status == STATUS_OK, loader.__name__


@pytest.mark.parametrize(
    ("label", "fail_on"),
    [
        # (a) between two artifacts of PASS 1 (immutable/run-stamped writes).
        ("between_pass1_artifacts", lambda name: name.startswith("performance_output_")),
        # (b) between PASS 1 and PASS 2 (the diagnostics write sits on the seam).
        ("between_pass1_and_pass2", lambda name: name == LINEARITY_DIAGNOSTICS_FILE_NAME),
    ],
)
def test_a_failed_publish_never_flips_any_alias(stage_env, monkeypatch, label, fail_on):
    """Publication is all-or-nothing across ALL FOUR artifacts.

    A crash anywhere in pass 1 must leave every alias -- gold_response included
    -- pointing at the previous complete generation.
    """

    paths = stage_env["paths"]
    before = _published_generation(stage_env)
    manifest_before = paths.latest_model_state_manifest_path.read_bytes()

    real_write = persist_module.write_parquet_atomic
    calls: list[str] = []

    def failing_write(frame, path):
        calls.append(path.name)
        if fail_on(path.name):
            raise OSError("injected fault")
        return real_write(frame, path)

    monkeypatch.setattr(persist_module, "write_parquet_atomic", failing_write)
    with pytest.raises(OSError, match="injected fault"):
        _run_stage(stage_env)

    assert label  # parametrize label kept for readable failure output
    # No alias write was even attempted before the fault.
    assert not [name for name in calls if name.endswith("_latest.parquet")]
    _assert_previous_generation_intact(paths, before, manifest_before)


def test_pass_one_writes_every_immutable_before_any_alias_flips(stage_env, monkeypatch):
    """Order gate: all eight run-stamped files precede the first alias write."""

    real_write = persist_module.write_parquet_atomic
    calls: list[str] = []

    def recording_write(frame, path):
        calls.append(path.name)
        return real_write(frame, path)

    monkeypatch.setattr(persist_module, "write_parquet_atomic", recording_write)
    _run_stage(stage_env)

    first_alias = min(
        index for index, name in enumerate(calls) if name.endswith("_latest.parquet")
    )
    pass_one = calls[:first_alias]
    for prefix in persist_module.TICKER_PAGE_ARTIFACT_PREFIXES:
        assert any(name.startswith(f"{prefix}_output_") for name in pass_one), prefix
        assert any(
            name.startswith(f"{prefix}_latest_") and name != f"{prefix}_latest.parquet"
            for name in pass_one
        ), prefix
    # And the tail is exactly the four alias flips.
    assert sorted(calls[first_alias:]) == sorted(
        f"{prefix}_latest.parquet"
        for prefix in persist_module.TICKER_PAGE_ARTIFACT_PREFIXES
    )


# ---------------------------------------------------------------------------
# 8. loader hardening (schema_version + unreadable manifest)
# ---------------------------------------------------------------------------


def test_an_unreadable_model_state_manifest_reads_corrupt_not_pending(stage_env):
    """A manifest that exists but cannot be parsed is CORRUPT, never PENDING.

    PENDING_FIRST_PUBLISH tells the user "wait for the next refresh" -- exactly
    the wrong instruction when a refresh already ran and its manifest is broken.
    """

    paths = stage_env["paths"]
    _published_generation(stage_env)
    assert load_gold_response(paths).status == STATUS_OK  # healthy control

    paths.latest_model_state_manifest_path.write_text("{not json", encoding="utf-8")
    for loader in (
        load_gold_response,
        load_score_percentiles,
        load_performance_series,
        load_research_series,
    ):
        state = loader(paths)
        assert state.status == STATUS_CORRUPT, loader.__name__
        assert "model-state manifest unreadable" in (state.reason or "")

    # A manifest that is READABLE but simply has no entry stays PENDING.
    paths.latest_model_state_manifest_path.write_text(
        json.dumps({"artifacts": {}}), encoding="utf-8"
    )
    assert load_gold_response(paths).status == STATUS_PENDING_FIRST_PUBLISH


def test_a_missing_schema_version_reads_corrupt(stage_env):
    paths = stage_env["paths"]
    _published_generation(stage_env)
    assert load_gold_response(paths).status == STATUS_OK  # healthy control

    _rewrite_published(stage_env, "gold_response", lambda frame: frame.drop(columns=["schema_version"]))
    state = load_gold_response(paths)
    assert state.status == STATUS_CORRUPT
    assert "schema_version" in (state.reason or "")
    # Control: an untouched artifact still reads OK.
    assert load_score_percentiles(paths).status == STATUS_OK


def test_an_unparsable_schema_version_reads_corrupt(stage_env):
    paths = stage_env["paths"]
    _published_generation(stage_env)

    def _garble(frame):
        frame = frame.copy()
        frame["schema_version"] = "not-a-version"
        return frame

    _rewrite_published(stage_env, "gold_response", _garble)
    state = load_gold_response(paths)
    assert state.status == STATUS_CORRUPT
    assert "unparsable schema_version" in (state.reason or "")


def test_a_different_schema_version_reads_stale_and_names_both_versions(stage_env):
    paths = stage_env["paths"]
    _published_generation(stage_env)

    def _bump(frame):
        frame = frame.copy()
        frame["schema_version"] = 99
        return frame

    _rewrite_published(stage_env, "gold_response", _bump)
    state = load_gold_response(paths)
    assert state.status == STATUS_STALE
    assert "99" in (state.reason or "")
    assert "2" in (state.reason or "")
    assert state.frame.empty
    assert load_score_percentiles(paths).status == STATUS_OK  # healthy control


def _rewrite_published(stage_env, prefix: str, transform) -> None:
    """Rewrite the published immutable in place and re-publish model state."""

    paths = stage_env["paths"]
    for path in sorted(paths.output_ticker_page_dir.glob(f"{prefix}_*.parquet")):
        transform(pd.read_parquet(path)).to_parquet(path, index=False)
    write_current_model_state_manifest(
        paths=paths,
        config_hash=stage_env["config_hash"],
        parent_refresh_id=FOUNDATION_RUN_ID,
        stage_timings={},
    )


# ---------------------------------------------------------------------------
# 9. schema-typed empty frames
# ---------------------------------------------------------------------------


def test_empty_and_populated_artifacts_round_trip_with_identical_dtypes(stage_env, tmp_path):
    """A degraded (zero-row) build must not silently change the persisted schema."""

    paths = stage_env["paths"]
    _run_stage(stage_env)

    for artifact, prefix in (
        ("gold_response", "gold_response"),
        ("percentiles", "percentiles"),
        ("performance", "performance"),
        ("research_series", "research_series"),
    ):
        populated_path = paths.output_ticker_page_dir / f"{prefix}_latest.parquet"
        populated = pd.read_parquet(populated_path)
        if populated.empty:
            continue

        empty = stamp_ticker_page_provenance(
            empty_artifact_frame(artifact),
            artifact=artifact,
            source_run_id="r",
            snapshot_refresh_run_id="r",
            parent_refresh_id="r",
            config_hash="c",
        )
        empty_path = tmp_path / f"empty_{prefix}.parquet"
        empty.to_parquet(empty_path, index=False)
        round_tripped = pd.read_parquet(empty_path)

        assert list(round_tripped.columns) == list(populated.columns), artifact
        for column in populated.columns:
            assert str(round_tripped[column].dtype) == str(populated[column].dtype), (
                artifact,
                column,
                str(round_tripped[column].dtype),
                str(populated[column].dtype),
            )
