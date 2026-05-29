from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths


def test_load_app_config_reads_repo_yaml():
    loaded = load_app_config(ProjectPaths.discover())

    assert len(loaded.app.universe.tickers) >= 5
    assert [benchmark.ticker for benchmark in loaded.app.benchmarks.benchmarks] == ["GDX", "GDXJ"]
    assert "benchmarks" in loaded.file_hashes
    assert loaded.app.horizons.core_horizons[0] == "5D"
    assert loaded.app.qa.near_zero_gold_return_threshold == 0.005
    assert 4000 in loaded.app.screening_params.gold_price_scenarios
    assert len(loaded.combined_hash) == 64
