"""Schema-v2 store tests: v1->v2 read-migration, no-rewrite-on-read, backup on
first v2 write, v2 round-trip with a distinct cost currency, version rejection.
"""

import json
from datetime import date

import pytest

from golden_vector.portfolio.manual_store import add_lot, load_lots
from golden_vector.portfolio.models import PortfolioValidationError, TickerInfo
from tests.helpers import build_test_paths

_V1_LOT = {
    "id": "lot-1",
    "ticker": "AAR.AX",
    "shares": 100,
    "buy_price": 2.0,
    "buy_currency": "AUD",
    "buy_date": "2020-01-01",
    "note": None,
    "created_at": "2020-01-01T00:00:00+00:00",
    "updated_at": "2020-01-01T00:00:00+00:00",
}


def _write_store(paths, payload) -> None:
    path = paths.manual_portfolio_lots_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_v1_store_migrates_to_v2_in_memory_on_read(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_store(paths, {"schema_version": 1, "lots": [_V1_LOT]})

    lot = load_lots(paths)[0]

    assert lot.cost_currency == "AUD"                       # cost ccy == quote ccy for v1
    assert lot.cost_basis_total == pytest.approx(200.0)     # 100 * 2.0
    assert lot.raw_broker_symbol == "AAR.AX"
    assert lot.source_name == "manual"
    assert lot.cost_basis_as_of_date == date(2020, 1, 1)
    # Read must NOT rewrite the file (A1): on disk it is still v1.
    assert json.loads(paths.manual_portfolio_lots_path.read_text())["schema_version"] == 1


def test_add_lot_on_v1_store_writes_v2_and_backs_up(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_store(paths, {"schema_version": 1, "lots": []})
    info = {"AAZ.L": TickerInfo(ticker="AAZ.L", currency="GBP", active=True)}

    add_lot(
        paths,
        {"ticker": "AAZ.L", "shares": "10", "buy_price": "2.5", "buy_currency": "GBP", "buy_date": "2020-01-01"},
        ticker_info=info,
    )

    on_disk = json.loads(paths.manual_portfolio_lots_path.read_text())
    assert on_disk["schema_version"] == 2
    assert on_disk["lots"][0]["cost_currency"] == "GBP"
    assert on_disk["lots"][0]["cost_basis_total"] == pytest.approx(25.0)
    assert on_disk["lots"][0]["source_name"] == "manual"
    backups = list(paths.manual_portfolio_lots_path.parent.glob("manual_lots.backup-v1-*.json"))
    assert len(backups) == 1


def test_v2_round_trip_preserves_distinct_cost_currency(tmp_path):
    paths = build_test_paths(tmp_path)
    v2_lot = {
        **_V1_LOT,
        "cost_currency": "GBP",          # GBP cost on an AUD-quoted ticker (the Snowball case)
        "cost_basis_total": 136.0,
        "raw_broker_symbol": "AAR",
        "source_name": "snowball",
        "source_file": "Snowball Holdings.csv",
        "cost_basis_as_of_date": "2026-06-15",
    }
    _write_store(paths, {"schema_version": 2, "lots": [v2_lot]})

    lot = load_lots(paths)[0]

    assert lot.buy_currency == "AUD"                 # quote currency preserved
    assert lot.cost_currency == "GBP"                # cost currency distinct
    assert lot.cost_basis_total == pytest.approx(136.0)
    assert lot.cost_per_share == pytest.approx(1.36)
    assert lot.source_name == "snowball"
    assert lot.raw_broker_symbol == "AAR"
    assert lot.cost_basis_as_of_date == date(2026, 6, 15)


def test_unknown_store_version_rejected(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_store(paths, {"schema_version": 99, "lots": []})

    with pytest.raises(PortfolioValidationError, match="not supported"):
        load_lots(paths)
