from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from golden_vector.app.config import load_app_config
from golden_vector.app.run_context import RunContext
from golden_vector.app.run_pruning import prune_runs
from golden_vector.contracts.fundamentals import (
    FETCHED_FUNDAMENTALS_SCHEMA_VERSION,
    FUNDAMENTALS_OFFICIAL_ARTIFACT_NAME,
    RAW_FUNDAMENTALS_STATEMENTS_COLUMNS,
    fetched_fundamentals_latest_path,
    fundamentals_fetch_manifest_run_stamped_path,
    raw_fundamentals_statements_latest_path,
    raw_fundamentals_history_latest_path,
)
from golden_vector.fundamentals.artifacts import (
    load_official_fundamentals,
    write_fetched_fundamentals_artifact_pair,
)
from golden_vector.fundamentals.fetch import fetch_and_publish_fundamentals
from golden_vector.fundamentals.history_store import (
    merge_raw_fundamentals_history,
    write_raw_fundamentals_history_artifact_pair,
)
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
    assert row["period_type"] == "ANNUAL"
    assert row["value_raw"] == 500_000_000.0


def test_mapper_converts_currency_then_scales_to_millions_once(tmp_path):
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
    interest_components = json.loads(rows.loc["interest_expense_musd", "components_json"])
    assert interest_components[0]["normalized_value"] == 25.0


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


def test_mapper_missing_one_split_debt_leg_is_missing_not_understated(tmp_path):
    source_run_id = "20260610T120000Z-fetch-fundamentals"
    payload = _payload(currency="USD")
    payload["balance_sheet"] = pd.DataFrame(
        {
            "2025-12-31": {
                "Long Term Debt": 450_000_000.0,
                "Cash And Cash Equivalents": 50_000_000.0,
            }
        }
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


def test_mapper_missing_cash_leg_keeps_debt_value_but_degrades_status(tmp_path):
    source_run_id = "20260610T120000Z-fetch-fundamentals"
    payload = _payload(currency="USD")
    payload["balance_sheet"] = pd.DataFrame(
        {"2025-12-31": {"Total Debt": 500_000_000.0}}
    )
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

    row = official[official["field_name"].eq("net_debt_musd")].iloc[0]
    assert row["value"] == 500.0
    assert row["value_status"] == "MISSING"
    assert row["statement_scale"] == "absolute_to_usd_millions_cash_missing_assumed_zero"
    assert row["value_origin"] == "cash_missing_assumed_zero"
    components = json.loads(row["components_json"])
    assert components[0]["component"] == "total_debt"
    assert components[0]["yahoo_line_item"] == "Total Debt"
    assert components[1]["component"] == "cash"
    assert components[1]["status"] == "MISSING_ASSUMED_ZERO"


def test_mapper_net_cash_miner_stays_net_cash_when_cash_is_present(tmp_path):
    source_run_id = "20260610T120000Z-fetch-fundamentals"
    payload = _payload(currency="USD")
    payload["balance_sheet"] = pd.DataFrame(
        {
            "2025-12-31": {
                "Total Debt": 100_000_000.0,
                "Cash And Cash Equivalents": 500_000_000.0,
            }
        }
    )
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

    row = official[official["field_name"].eq("net_debt_musd")].iloc[0]
    assert row["value"] == -400.0
    assert row["value_status"] == "OK"


def test_mapper_rejects_cross_period_ebitda_and_da_mix(tmp_path):
    source_run_id = "20260610T120000Z-fetch-fundamentals"
    payload = _payload(currency="USD")
    payload["cashflow"] = pd.DataFrame(
        {
            "2024-12-31": {
                "Depreciation And Amortization": 100_000_000.0,
            }
        }
    )
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

    rows = official.set_index("field_name")
    assert pd.isna(rows.loc["ebitda_ltm_musd", "value"])
    assert rows.loc["ebitda_ltm_musd", "value_status"] == "MISSING"
    assert pd.isna(rows.loc["da_musd", "value"])
    assert rows.loc["da_musd", "value_status"] == "MISSING"


def test_mapper_annual_statement_fields_are_labeled_annual_not_ttm(tmp_path):
    source_run_id = "20260610T120000Z-fetch-fundamentals"
    raw = raw_statement_payload_to_frame(
        ticker="AEM",
        yahoo_symbol="AEM",
        payload=_payload(currency="USD"),
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

    rows = official.set_index("field_name")
    assert rows.loc["ebitda_ltm_musd", "period_type"] == "ANNUAL"
    assert rows.loc["da_musd", "period_type"] == "ANNUAL"
    assert rows.loc["interest_expense_musd", "period_type"] == "ANNUAL"


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
    assert row["value_origin"] == "reported_field_diverged"
    components = json.loads(row["components_json"])
    assert [component["component"] for component in components] == [
        "operating_income",
        "depreciation_and_amortization",
        "reported_ebitda_cross_check",
    ]


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
    assert raw_fundamentals_history_latest_path(paths).exists()
    assert result.manifest["raw_statements"]["path"].endswith(".parquet")
    assert result.manifest["raw_history_artifact"]["row_count"] >= len(raw.index)
    assert result.manifest["summary"]["pass_count"] == 1
    assert set(official["field_name"]) == {
        "da_musd",
        "ebitda_ltm_musd",
        "interest_expense_musd",
        "net_debt_musd",
        "tax_rate",
    }


def test_raw_fundamentals_history_preserves_period_type_key(tmp_path):
    source_run_id = "20260610T120000Z-fetch-fundamentals"
    raw = raw_statement_payload_to_frame(
        ticker="AEM",
        yahoo_symbol="AEM",
        payload=_payload(currency="USD"),
        fetched_at_utc="2026-06-10T12:00:00Z",
        source_run_id=source_run_id,
    )
    history = merge_raw_fundamentals_history(
        existing=None,
        incoming=raw,
        source_run_id=source_run_id,
    )
    updated = raw.copy()
    mask = updated["line_item_original"].eq("Operating Income")
    updated.loc[mask, "value_raw"] = 600_000_000.0
    updated.loc[mask, "fetched_at_utc"] = "2026-06-11T12:00:00Z"
    updated.loc[mask, "source_run_id"] = "20260611T120000Z-fetch-fundamentals"
    quarterly = updated.loc[mask].copy()
    quarterly["period_type"] = "QUARTERLY"

    merged = merge_raw_fundamentals_history(
        existing=history,
        incoming=pd.concat([updated, quarterly], ignore_index=True),
        source_run_id="20260611T120000Z-fetch-fundamentals",
    )

    rows = merged[
        merged["statement_type"].eq("income_stmt")
        & merged["line_item_original"].eq("Operating Income")
        & merged["period_end"].astype(str).eq("2025-12-31")
    ].sort_values("period_type")
    assert rows["period_type"].tolist() == ["ANNUAL", "QUARTERLY"]
    annual = rows[rows["period_type"].eq("ANNUAL")].iloc[0]
    assert annual["value_raw"] == 600_000_000.0
    assert annual["first_seen_source_run_id"] == source_run_id
    assert annual["last_seen_source_run_id"] == "20260611T120000Z-fetch-fundamentals"


def test_raw_fundamentals_history_fails_loud_on_corrupt_latest(tmp_path):
    paths = build_test_paths(tmp_path)
    source_run_id = "20260610T120000Z-fetch-fundamentals"
    raw = raw_statement_payload_to_frame(
        ticker="AEM",
        yahoo_symbol="AEM",
        payload=_payload(currency="USD"),
        fetched_at_utc="2026-06-10T12:00:00Z",
        source_run_id=source_run_id,
    )
    raw_fundamentals_history_latest_path(paths).parent.mkdir(parents=True, exist_ok=True)
    raw_fundamentals_history_latest_path(paths).write_text("not parquet", encoding="utf-8")

    with pytest.raises(ValueError, match="raw fundamentals history could not be read"):
        write_raw_fundamentals_history_artifact_pair(
            paths=paths,
            incoming=raw,
            source_run_id=source_run_id,
        )


def test_fetch_stage_isolates_per_ticker_statement_exception(tmp_path):
    paths = build_test_paths(tmp_path)
    loaded_config = load_app_config(paths)
    run_context = RunContext.start(
        paths=paths,
        command="fetch-fundamentals",
        parameters={"tickers": ["AEM", "NEM"]},
        config_hash=loaded_config.config_hash,
    )
    fake_client = _FakeYahooClient(
        {"AEM": _payload(currency="USD")},
        raised_symbols={"NEM"},
    )

    result = fetch_and_publish_fundamentals(
        paths=paths,
        app_config=loaded_config.app,
        run_context=run_context,
        yahoo_client=fake_client,
        tickers=["AEM", "NEM"],
    )

    raw = load_raw_fundamentals_statements(paths, source_run_id=result.source_run_id)
    official = load_official_fundamentals(paths)
    failed_raw = raw[raw["ticker"].eq("NEM")].iloc[0]
    assert result.manifest["summary"]["pass_count"] == 1
    assert result.manifest["summary"]["fail_count"] == 1
    assert failed_raw["fetch_status"] == "FAIL"
    assert "Yahoo statement fetch failed" in failed_raw["error_message"]
    assert set(official["ticker"]) == {"AEM", "NEM"}
    failed_official = official[official["ticker"].eq("NEM")]
    assert set(failed_official["value_status"]) == {"MISSING"}


def test_full_fundamentals_outage_writes_run_artifacts_without_advancing_current(tmp_path):
    paths = build_test_paths(tmp_path)
    loaded_config = load_app_config(paths)
    prior_source_run_id = "20260609T120000Z-fetch-fundamentals"
    write_fetched_fundamentals_artifact_pair(
        paths=paths,
        frame=pd.DataFrame(
            [
                {
                    "schema_version": FETCHED_FUNDAMENTALS_SCHEMA_VERSION,
                    "ticker": "AEM",
                    "field_name": "net_debt_musd",
                    "value": 250.0,
                    "source": "YAHOO",
                    "source_run_id": prior_source_run_id,
                    "fetched_at_utc": "2026-06-09T12:00:00Z",
                    "statement_period": "FY2025",
                    "period_end": date(2025, 12, 31),
                    "period_type": "ANNUAL",
                    "statement_currency": "USD",
                    "statement_scale": "absolute_to_usd_millions",
                    "value_status": "OK",
                }
            ]
        ),
        source_run_id=prior_source_run_id,
    )
    latest_before = fetched_fundamentals_latest_path(paths).read_bytes()
    run_context = RunContext.start(
        paths=paths,
        command="fetch-fundamentals",
        parameters={"tickers": ["AEM", "NEM"]},
        config_hash=loaded_config.config_hash,
    )
    fake_client = _FakeYahooClient({}, raised_symbols={"AEM", "NEM"})

    result = fetch_and_publish_fundamentals(
        paths=paths,
        app_config=loaded_config.app,
        run_context=run_context,
        yahoo_client=fake_client,
        tickers=["AEM", "NEM"],
    )

    assert result.manifest["stage_timings"]["current_publish_blocked_reason"] == (
        "full_yahoo_outage"
    )
    assert fetched_fundamentals_latest_path(paths).read_bytes() == latest_before
    assert not raw_fundamentals_statements_latest_path(paths).exists()
    assert not paths.latest_fundamentals_fetch_manifest_path.exists()
    assert paths.resolve_repo_relative(result.manifest["official_artifact"]["path"]).exists()


def test_partial_fetch_writes_run_stamped_artifacts_without_current_aliases(tmp_path):
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
        publish_current=False,
    )

    raw_path = paths.resolve_repo_relative(result.manifest["raw_statements"]["path"])
    official_path = paths.resolve_repo_relative(result.manifest["official_artifact"]["path"])
    assert raw_path.exists()
    assert official_path.exists()
    assert fundamentals_fetch_manifest_run_stamped_path(paths, result.source_run_id).exists()
    assert result.manifest["raw_statements"]["latest_alias_path"] is None
    assert "latest_alias_path" not in result.manifest["official_artifact"]
    assert not raw_fundamentals_statements_latest_path(paths).exists()
    assert not fetched_fundamentals_latest_path(paths).exists()
    assert not paths.latest_fundamentals_fetch_manifest_path.exists()


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
    def __init__(
        self,
        payloads: dict[str, dict[str, object]],
        *,
        raised_symbols: set[str] | None = None,
    ) -> None:
        self._payloads = payloads
        self._raised_symbols = raised_symbols or set()

    def fetch_financial_statements(self, symbol: str) -> dict[str, object]:
        if symbol in self._raised_symbols:
            raise RuntimeError(f"boom for {symbol}")
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
