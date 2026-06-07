import argparse

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.cli import run_manual_data, run_manual_note
from golden_vector.screening.manual_data import (
    bootstrap_manual_screening_data,
    load_manual_screening_data,
)
from golden_vector.screening.manual_store import list_stock_notes
from tests.helpers import build_test_paths


class _LoadedConfigStub:
    def __init__(self, app: object, config_hash: str) -> None:
        self.app = app
        self.config_hash = config_hash


def test_run_manual_data_set_company_updates_store(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, config_hash="hash"),
    )

    exit_code = run_manual_data(
        paths,
        argparse.Namespace(
            command="manual-data",
            manual_data_command="set-company",
            ticker="NEM",
            production_oz=6_000_000.0,
            aisc_usd_per_oz=1300.0,
            cash_cost_usd_per_oz=None,
            royalty_rate=None,
            sustaining_capex_musd=None,
            da_musd=None,
            interest_expense_musd=None,
            tax_rate=None,
            reserve_life_years=None,
            net_debt_musd=None,
            ebitda_ltm_musd=None,
        ),
    )

    assert exit_code == 0
    loaded = load_manual_screening_data(paths, tickers=["NEM"])
    row = loaded.company_inputs[loaded.company_inputs["ticker"] == "NEM"].iloc[0]
    assert float(row["production_oz"]) == 6_000_000.0
    assert float(row["aisc_usd_per_oz"]) == 1300.0


def test_run_manual_data_show_fails_cleanly_when_store_is_missing(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app
    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, config_hash="hash"),
    )

    exit_code = run_manual_data(
        paths,
        argparse.Namespace(
            command="manual-data",
            manual_data_command="show",
            ticker="NEM",
        ),
    )

    assert exit_code == 1


def test_run_manual_data_set_company_can_clear_existing_values(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, config_hash="hash"),
    )

    run_manual_data(
        paths,
        argparse.Namespace(
            command="manual-data",
            manual_data_command="set-company",
            ticker="NEM",
            production_oz=6_000_000.0,
            aisc_usd_per_oz=1300.0,
            cash_cost_usd_per_oz=None,
            royalty_rate=None,
            sustaining_capex_musd=None,
            da_musd=None,
            interest_expense_musd=None,
            tax_rate=None,
            reserve_life_years=None,
            net_debt_musd=None,
            ebitda_ltm_musd=None,
            clear_fields=[],
        ),
    )

    exit_code = run_manual_data(
        paths,
        argparse.Namespace(
            command="manual-data",
            manual_data_command="set-company",
            ticker="NEM",
            production_oz=None,
            aisc_usd_per_oz=None,
            cash_cost_usd_per_oz=None,
            royalty_rate=None,
            sustaining_capex_musd=None,
            da_musd=None,
            interest_expense_musd=None,
            tax_rate=None,
            reserve_life_years=None,
            net_debt_musd=None,
            ebitda_ltm_musd=None,
            clear_fields=["production_oz"],
        ),
    )

    assert exit_code == 0
    loaded = load_manual_screening_data(paths, tickers=["NEM"])
    row = loaded.company_inputs[loaded.company_inputs["ticker"] == "NEM"].iloc[0]
    assert pd.isna(row["production_oz"])
    assert float(row["aisc_usd_per_oz"]) == 1300.0


def test_run_manual_note_add_and_list_use_local_store(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, config_hash="hash"),
    )

    add_exit_code = run_manual_note(
        paths,
        argparse.Namespace(
            command="manual-note",
            manual_note_command="add",
            ticker="NEM",
            note="Recheck after next production report",
            tag="FOLLOW_UP",
            status="OPEN",
        ),
    )

    assert add_exit_code == 0
    note_rows = list_stock_notes(paths, ticker="NEM", limit=10)
    assert len(note_rows.index) == 1
    assert note_rows.iloc[0]["note_tag"] == "FOLLOW_UP"

    list_exit_code = run_manual_note(
        paths,
        argparse.Namespace(
            command="manual-note",
            manual_note_command="list",
            ticker="NEM",
            limit=10,
        ),
    )

    assert list_exit_code == 0
