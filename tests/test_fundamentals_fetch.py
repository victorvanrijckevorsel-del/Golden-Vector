from __future__ import annotations

import json
from datetime import date

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.run_context import RunContext
from golden_vector.app.run_pruning import prune_runs
from golden_vector.contracts.fundamentals import (
    FUNDAMENTALS_OFFICIAL_ARTIFACT_NAME,
    RAW_FUNDAMENTALS_STATEMENTS_COLUMNS,
    raw_fundamentals_statements_latest_path,
)
from golden_vector.fundamentals.artifacts import load_official_fundamentals
from golden_vector.fundamentals.fetch import fetch_and_publish_fundamentals
from golden_vector.fundamentals.mapper import map_raw_fundamentals_to_official
from golden_vector.fundamentals.raw_store import (
    load_raw_fundamentals_statements,
    raw_statement_payload_to_frame,
    write_fundamentals_fetch_manifest,
    write_raw_fundamentals_artifact_pair,
)
from golden_vector.ingestion.yahoo_client import YahooClient
from tests.helpers import build_test_paths


def test_raw_fundamentals_round_trip_preserves_yahoo_lines_periods_currency_and_values(tmp_path):
    paths = build_test_paths(tmp_path)
    source_run_id = "20260610T120000Z-fetch-fundamentals"
    raw = raw_statement_payload_to_frame(
        ticker="AEM",
        yahoo_symbol="AEM",
        payload=_payload(currency="USD"),
        fetched_at_utc="2026-06-10T12:00:00Z",
        source_run_id=source_run_id,
    )

    write_raw_fundamentals_artifact_pair(
        paths=paths,
        frame=raw,
        source_run_id=source_run_id,
    )
    loaded = load_raw_fundamentals_statements(paths, source_run_id=source_run_id)

    assert list(loaded.columns) == list(RAW_FUNDAMENTALS_STATEMENTS_COLUMNS)
    row = loaded[
        loaded["statement_type"].eq("income_stmt")
        & loaded["line_item_original"].eq("Operating Income")
    ].iloc[0]
    assert row["ticker"] == "AEM"
    assert row["financial_currency"] == "USD"
    assert row["period_end"] == date(2025, 12, 31)
    assert row["value_raw"] == 500_000_000.0


def test_mapper_converts_currency_then_scales_to_millions_once(tmp_path):
    paths = build_test_paths(tmp_path)
    source_run_id = "20260610T120000Z-fetch-fundamentals"
    raw = raw_statement_payload_to_frame(
        ticker="AAZ.L",
        yahoo_symbol="AAZ.L",
        payload=_payload(currency="GBP"),
        fetched_at_utc="2026-06-10T12:00:00Z",
        source_run_id=source_run_id,
    )
    fx = pd.DataFrame(
        [
            {
                "date": date(2025, 12, 31),
                "fx_rate_to_usd": 1.25,
                "source_symbol": "GBPUSD=X",
            }
        ]
    )

    official = map_raw_fundamentals_to_official(
        raw,
        fx_histories={"GBP": fx},
        source_run_id=source_run_id,
        max_statement_age_days=540,
        ebitda_reconciliation_max_pct=0.25,
    )

    rows = official.set_index("field_name")
    assert rows.loc["net_debt_musd", "value"] == 500.0
    assert rows.loc["net_debt_musd", "value_status"] == "OK"
    assert rows.loc["ebitda_ltm_musd", "value"] == 750.0
    assert rows.loc["da_musd", "value"] == 125.0
    assert rows.loc["interest_expense_musd", "value"] == 25.0


def test_mapper_missing_debt_leg_is_missing_not_zero_strength(tmp_path):
    source_run_id = "20260610T120000Z-fetch-fundamentals"
    payload = _payload(currency="USD")
    payload["balance_sheet"] = pd.DataFrame(
        {"2025-12-31": {"Cash And Cash Equivalents": 50_000_000.0}}
    )
    raw = raw_statement_payload_to_frame(
        ticker="NEM",
        yahoo_symbol="NEM",
        payload=payload,
        fetched_at_utc="2026-06-10T12:00:00Z",
        source_run_id=source_run_id,
    )

    official = map_raw_fundamentals_to_official(
        raw,
        fx_histories={},
        source_run_id=source_run_id,
        max_statement_age_days=540,
        ebitda_reconciliation_max_pct=0.25,
    )

    row = official[official["field_name"].eq("net_debt_musd")].iloc[0]
    assert pd.isna(row["value"])
    assert row["value_status"] == "MISSING"


def test_mapper_marks_divergent_reported_ebitda_contaminated(tmp_path):
    source_run_id = "20260610T120000Z-fetch-fundamentals"
    payload = _payload(currency="USD")
    payload["income_stmt"].loc["EBITDA", "2025-12-31"] = 1_500_000_000.0
    raw = raw_statement_payload_to_frame(
        ticker="AEM",
        yahoo_symbol="AEM",
        payload=payload,
        fetched_at_utc="2026-06-10T12:00:00Z",
        source_run_id=source_run_id,
    )

    official = map_raw_fundamentals_to_official(
        raw,
        fx_histories={},
        source_run_id=source_run_id,
        max_statement_age_days=540,
        ebitda_reconciliation_max_pct=0.25,
    )

    row = official[official["field_name"].eq("ebitda_ltm_musd")].iloc[0]
    assert row["value"] == 600.0
    assert row["value_status"] == "CONTAMINATED"


def test_fetch_stage_persists_raw_then_maps_from_storage(tmp_path):
    paths = build_test_paths(tmp_path)
    loaded_config = load_app_config(paths)
    run_context = RunContext.start(
        paths=paths,
        command="fetch-fundamentals",
        parameters={"tickers": ["AEM"]},
        config_hash=loaded_config.config_hash,
    )
    fake_client = _FakeYahooClient({"AEM": _payload(currency="USD")})

    result = fetch_and_publish_fundamentals(
        paths=paths,
        app_config=loaded_config.app,
        run_context=run_context,
        yahoo_client=fake_client,
        tickers=["AEM"],
    )

    raw = load_raw_fundamentals_statements(paths, source_run_id=result.source_run_id)
    official = load_official_fundamentals(paths)
    assert result.raw_row_count == len(raw.index)
    assert result.official_row_count == len(official.index)
    assert raw_fundamentals_statements_latest_path(paths).exists()
    assert result.manifest["raw_statements"]["path"].endswith(".parquet")
    assert result.manifest["summary"]["pass_count"] == 1
    assert set(official["field_name"]) == {
        "da_musd",
        "ebitda_ltm_musd",
        "interest_expense_musd",
        "net_debt_musd",
        "tax_rate",
    }


def test_yahoo_client_fetch_financial_statements_uses_properties_and_returns_currency():
    fake_yf = _FakeYFinance()
    client = YahooClient(yf_module=fake_yf)

    payload = client.fetch_financial_statements("AEM")

    assert payload["financialCurrency"] == "USD"
    assert isinstance(payload["income_stmt"], pd.DataFrame)
    assert isinstance(payload["balance_sheet"], pd.DataFrame)
    assert isinstance(payload["cashflow"], pd.DataFrame)


def test_prune_runs_preserves_raw_fundamentals_referenced_by_fetch_manifest(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    source_run_id = "20260610T120000Z-fetch-fundamentals"
    raw = raw_statement_payload_to_frame(
        ticker="AEM",
        yahoo_symbol="AEM",
        payload=_payload(currency="USD"),
        fetched_at_utc="2026-06-10T12:00:00Z",
        source_run_id=source_run_id,
    )
    write = write_raw_fundamentals_artifact_pair(
        paths=paths,
        frame=raw,
        source_run_id=source_run_id,
    )
    write_fundamentals_fetch_manifest(
        paths=paths,
        source_run_id=source_run_id,
        fetched_at_utc="2026-06-10T12:00:00Z",
        raw_run_path=write.run_path,
        raw_latest_path=write.latest_path,
        ticker_statuses=[{"ticker": "AEM", "status": "PASS", "raw_row_count": len(raw.index)}],
        timings={"fetch_seconds": 1.0},
    )
    _write_protectable_model_state(paths)

    report = prune_runs(paths, keep_model_states=1, apply=True)

    raw_path = paths.resolve_repo_relative(write.run_path)
    assert raw_path.exists()
    assert all(candidate.path != raw_path for candidate in report.candidates)


def _payload(*, currency: str) -> dict[str, object]:
    return {
        "financialCurrency": currency,
        "income_stmt": pd.DataFrame(
            {
                "2025-12-31": {
                    "Operating Income": 500_000_000.0,
                    "Interest Expense": -20_000_000.0,
                    "EBITDA": 600_000_000.0,
                }
            }
        ),
        "balance_sheet": pd.DataFrame(
            {
                "2025-12-31": {
                    "Total Debt": 500_000_000.0,
                    "Cash And Cash Equivalents": 100_000_000.0,
                }
            }
        ),
        "cashflow": pd.DataFrame(
            {
                "2025-12-31": {
                    "Depreciation And Amortization": 100_000_000.0,
                }
            }
        ),
    }


class _FakeYahooClient:
    def __init__(self, payloads: dict[str, dict[str, object]]) -> None:
        self._payloads = payloads

    def fetch_financial_statements(self, symbol: str) -> dict[str, object]:
        return self._payloads.get(symbol, {})


class _FakeTicker:
    financial_currency = "USD"

    @property
    def income_stmt(self) -> pd.DataFrame:
        return _payload(currency="USD")["income_stmt"]

    @property
    def balance_sheet(self) -> pd.DataFrame:
        return _payload(currency="USD")["balance_sheet"]

    @property
    def cashflow(self) -> pd.DataFrame:
        return _payload(currency="USD")["cashflow"]


class _FakeYFinance:
    def Ticker(self, symbol: str) -> _FakeTicker:  # noqa: N802 - mirrors yfinance.
        return _FakeTicker()


def _write_protectable_model_state(paths) -> None:
    paths.model_state_manifests_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at_utc": "2026-06-10T12:00:00Z",
        "artifacts": {
            FUNDAMENTALS_OFFICIAL_ARTIFACT_NAME: {
                "path": (
                    "data/output/fundamentals/"
                    "fetched_fundamentals_latest_20260610T120000Z-fetch-fundamentals.parquet"
                ),
                "source_run_ids": ["20260610T120000Z-fetch-fundamentals"],
            }
        },
    }
    path = paths.model_state_manifests_dir / "model_state_current.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    paths.latest_model_state_manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
