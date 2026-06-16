"""Schema-v2 store tests: v1->v2 read-migration, no-rewrite-on-read, backup on
first v2 write, v2 round-trip with a distinct cost currency, version rejection.
"""

import json
from datetime import date

import pytest

from golden_vector.portfolio.manual_store import add_lot, delete_lot, edit_lot, load_lots
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


_V2_DISTINCT_LOT = {
    **_V1_LOT,
    "cost_currency": "GBP",          # GBP cost on an AUD-quoted ticker
    "cost_basis_total": 136.0,
    "raw_broker_symbol": "AAR",
    "source_name": "snowball",
    "source_file": "Snowball Holdings.csv",
    "cost_basis_as_of_date": "2026-06-15",
}


@pytest.mark.parametrize(
    "drop_field",
    ["cost_currency", "cost_basis_total", "cost_basis_as_of_date", "raw_broker_symbol", "source_name"],
)
def test_v2_store_rejects_missing_required_field(tmp_path, drop_field):
    paths = build_test_paths(tmp_path)
    lot = {key: value for key, value in _V2_DISTINCT_LOT.items() if key != drop_field}
    _write_store(paths, {"schema_version": 2, "lots": [lot]})

    with pytest.raises(PortfolioValidationError):
        load_lots(paths)  # v2 must reject malformed money fields, never backfill from v1


def test_v2_store_rejects_unsupported_cost_currency(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_store(paths, {"schema_version": 2, "lots": [{**_V2_DISTINCT_LOT, "cost_currency": "XYZ"}]})

    with pytest.raises(PortfolioValidationError, match="cost_currency"):
        load_lots(paths)


def test_edit_lot_blocks_imported_distinct_cost_lot_and_preserves_it(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_store(paths, {"schema_version": 2, "lots": [_V2_DISTINCT_LOT]})
    info = {"AAR.AX": TickerInfo(ticker="AAR.AX", currency="AUD", active=True)}

    with pytest.raises(PortfolioValidationError, match="imported position"):
        edit_lot(
            paths,
            "lot-1",
            {"ticker": "AAR.AX", "shares": "100", "buy_price": "2.0", "buy_currency": "AUD", "buy_date": "2020-01-01"},
            ticker_info=info,
        )

    # The imported lot must survive the blocked edit unchanged.
    on_disk = json.loads(paths.manual_portfolio_lots_path.read_text())
    assert on_disk["lots"][0]["cost_currency"] == "GBP"
    assert on_disk["lots"][0]["source_name"] == "snowball"


def test_delete_lot_blocks_imported_distinct_cost_lot_and_preserves_it(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_store(paths, {"schema_version": 2, "lots": [_V2_DISTINCT_LOT]})

    # The legacy delete route must refuse imported/distinct-cost lots too, not just
    # edits -- otherwise the old manual page could shrink a real broker book.
    with pytest.raises(PortfolioValidationError, match="imported position"):
        delete_lot(paths, "lot-1")

    on_disk = json.loads(paths.manual_portfolio_lots_path.read_text())
    assert len(on_disk["lots"]) == 1                       # survived the blocked delete
    assert on_disk["lots"][0]["source_name"] == "snowball"


def test_v1_lot_with_unsupported_currency_fails_loud_not_bricks(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_store(paths, {"schema_version": 1, "lots": [{**_V1_LOT, "buy_currency": "XYZ"}]})
    # Must fail loud on first read (clear error), never silently migrate into an
    # unreadable v2 record that bricks the whole store on the next save.
    with pytest.raises(PortfolioValidationError, match="cost_currency must be one of"):
        load_lots(paths)
