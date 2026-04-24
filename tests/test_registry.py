from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.ingestion import registry as registry_module
from golden_vector.ingestion.registry import build_foundation_registry, missing_fx_currencies


def test_registry_builds_fx_targets_for_non_usd_currencies():
    loaded = load_app_config(ProjectPaths.discover())

    registry = build_foundation_registry(loaded.app.universe)

    fx_symbols = {target.yahoo_symbol for target in registry.fx_targets}
    expected_currencies = {
        ticker.currency for ticker in loaded.app.universe.tickers
        if ticker.active and ticker.currency != "USD"
    }
    expected_symbols = {f"{cur}USD=X" for cur in expected_currencies}
    assert fx_symbols == expected_symbols
    assert registry.gold_target.yahoo_symbol == "GC=F"


def test_registry_includes_market_snapshots_for_tool_b_tickers():
    loaded = load_app_config(ProjectPaths.discover())

    registry = build_foundation_registry(loaded.app.universe)

    expected = sum(
        1 for ticker in loaded.app.universe.tickers if ticker.active and ticker.tool_b_enabled
    )
    assert len(registry.market_snapshot_targets) == expected


def test_registry_reports_missing_fx_mappings_without_crashing(monkeypatch):
    loaded = load_app_config(ProjectPaths.discover())
    monkeypatch.delitem(registry_module.FX_SYMBOL_BY_CURRENCY, "CAD", raising=False)

    registry = build_foundation_registry(loaded.app.universe)

    assert missing_fx_currencies(loaded.app.universe) == ["CAD"]
    expected_remaining = {
        ticker.currency for ticker in loaded.app.universe.tickers
        if ticker.active and ticker.currency != "USD" and ticker.currency != "CAD"
    }
    assert {target.base_currency for target in registry.fx_targets} == expected_remaining


def test_registry_excludes_active_tickers_disabled_for_both_tools():
    loaded = load_app_config(ProjectPaths.discover())
    first_ticker = loaded.app.universe.tickers[0]
    disabled_ticker = first_ticker.model_copy(
        update={"tool_a_enabled": False, "tool_b_enabled": False}
    )
    patched_universe = loaded.app.universe.model_copy(
        update={"tickers": [disabled_ticker, *loaded.app.universe.tickers[1:]]}
    )

    registry = build_foundation_registry(patched_universe)

    assert first_ticker.ticker not in {target.ticker for target in registry.equity_targets}
