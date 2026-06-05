from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths


def test_load_app_config_reads_repo_yaml():
    loaded = load_app_config(ProjectPaths.discover())

    assert len(loaded.app.universe.tickers) >= 5
    assert [benchmark.ticker for benchmark in loaded.app.benchmarks.benchmarks] == ["GDX", "GDXJ"]
    assert "benchmarks" in loaded.file_hashes
    assert loaded.app.hedge_readiness.target_delta == -0.25
    assert "hedge_readiness" in loaded.file_hashes
    assert loaded.app.tool_c.min_events == 8
    assert loaded.app.tool_c.downside_hit_rate_threshold_pct == -10.0
    assert "tool_c" in loaded.file_hashes
    assert loaded.app.tool_d.max_reasonable_ev_ebitda == 100.0
    assert loaded.app.tool_d.quality_components["leverage_stressed_at_g"] == "low_good"
    assert "tool_d" in loaded.file_hashes
    assert loaded.app.horizons.core_horizons[0] == "5D"
    assert loaded.app.qa.near_zero_gold_return_threshold == 0.005
    assert 4000 in loaded.app.screening_params.gold_price_scenarios
    assert len(loaded.combined_hash) == 64
