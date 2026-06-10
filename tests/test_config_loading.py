import pytest

from golden_vector.app.config import PORTFOLIO_ENABLED_ENV, load_app_config
from golden_vector.app.paths import ProjectPaths
from tests.helpers import build_test_paths


def test_load_app_config_reads_repo_yaml(monkeypatch):
    monkeypatch.delenv(PORTFOLIO_ENABLED_ENV, raising=False)
    loaded = load_app_config(ProjectPaths.discover())

    assert len(loaded.app.universe.tickers) >= 5
    assert [benchmark.ticker for benchmark in loaded.app.benchmarks.benchmarks] == ["GDX", "GDXJ"]
    assert "benchmarks" in loaded.file_hashes
    assert loaded.app.market_data.yahoo_throttle_seconds == 0.15
    assert loaded.app.market_data.yahoo_backoff_jitter_seconds == 0.1
    assert loaded.app.market_data.yahoo_max_workers == 4
    assert "market_data" in loaded.file_hashes
    assert loaded.app.hedge_readiness.target_delta == -0.25
    assert "hedge_readiness" in loaded.file_hashes
    assert loaded.app.tool_c.min_events == 8
    assert loaded.app.tool_c.downside_hit_rate_threshold_pct == -10.0
    assert "tool_c" in loaded.file_hashes
    assert loaded.app.tool_d.max_reasonable_ev_ebitda == 100.0
    assert loaded.app.tool_d.version == 2
    assert loaded.app.tool_d.quality_components["leverage_stressed_at_g"] == "low_good"
    assert "tool_d" in loaded.file_hashes
    assert loaded.app.fundamentals.max_statement_age_days == 540
    assert loaded.app.fundamentals.ebitda_reconciliation_max_pct == 0.25
    assert "fundamentals" in loaded.file_hashes
    assert loaded.app.horizons.core_horizons[0] == "5D"
    assert loaded.app.qa.near_zero_gold_return_threshold == 0.005
    assert 4000 in loaded.app.screening_params.gold_price_scenarios
    assert loaded.app.portfolio.enabled is False
    assert len(loaded.config_hash) == 64


def test_portfolio_can_be_enabled_with_gitignored_local_override(tmp_path, monkeypatch):
    monkeypatch.delenv(PORTFOLIO_ENABLED_ENV, raising=False)
    paths = build_test_paths(tmp_path)
    (paths.config_dir / "portfolio.local.yaml").write_text("enabled: true\n", encoding="utf-8")

    loaded = load_app_config(paths)

    assert loaded.app.portfolio.enabled is True
    assert "portfolio_local" in loaded.file_hashes


def test_portfolio_env_override_wins_over_file_config(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    (paths.config_dir / "portfolio.local.yaml").write_text("enabled: false\n", encoding="utf-8")
    monkeypatch.setenv(PORTFOLIO_ENABLED_ENV, "yes")

    loaded = load_app_config(paths)

    assert loaded.app.portfolio.enabled is True
    assert "portfolio_env_override" in loaded.file_hashes


def test_portfolio_env_override_rejects_ambiguous_values(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    monkeypatch.setenv(PORTFOLIO_ENABLED_ENV, "maybe")

    with pytest.raises(ValueError, match=PORTFOLIO_ENABLED_ENV):
        load_app_config(paths)
