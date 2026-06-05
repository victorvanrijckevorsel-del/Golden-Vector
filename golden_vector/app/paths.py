"""Centralized path management."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectPaths:
    """Repository-relative paths used by the application."""

    repo_root: Path
    config_dir: Path
    data_dir: Path
    raw_dir: Path
    intermediate_dir: Path
    output_dir: Path
    manual_dir: Path
    runs_dir: Path
    reviews_dir: Path
    tests_dir: Path

    @classmethod
    def discover(cls) -> "ProjectPaths":
        repo_root = Path(__file__).resolve().parents[2]
        data_dir = repo_root / "data"
        return cls(
            repo_root=repo_root,
            config_dir=repo_root / "config",
            data_dir=data_dir,
            raw_dir=data_dir / "raw",
            intermediate_dir=data_dir / "intermediate",
            output_dir=data_dir / "output",
            manual_dir=data_dir / "manual",
            runs_dir=data_dir / "runs",
            reviews_dir=repo_root / "reviews",
            tests_dir=repo_root / "tests",
        )

    def ensure_runtime_dirs(self) -> None:
        for path in (
            self.config_dir,
            self.data_dir,
            self.raw_dir,
            self.intermediate_dir,
            self.output_dir,
            self.manual_dir,
            self.runs_dir,
            self.reviews_dir,
            self.tests_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

        for path in (
            self.raw_equities_dir,
            self.raw_fx_dir,
            self.raw_gold_dir,
            self.raw_market_snapshots_dir,
            self.raw_status_dir,
            self.manual_screening_dir,
            self.intermediate_usd_equities_dir,
            self.intermediate_market_snapshots_dir,
            self.intermediate_horizon_metrics_dir,
            self.intermediate_tool_a_structural_dir,
            self.intermediate_tool_a_profiles_dir,
            self.intermediate_tool_b_dir,
            self.intermediate_tool_c_dir,
            self.intermediate_tool_d_dir,
            self.options_features_dir,
            self.benchmarks_dir,
            self.intermediate_status_dir,
            self.output_tool_a_dir,
            self.output_tool_b_dir,
            self.output_tool_c_dir,
            self.output_tool_d_dir,
            self.output_options_dir,
            self.output_combined_dir,
            self.output_hedge_readiness_dir,
            self.manual_holdings_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def ensure_run_dir(self, run_id: str) -> Path:
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def config_path(self, file_name: str) -> Path:
        return self.config_dir / file_name

    def resolve_repo_relative(self, value: str) -> Path:
        return self.repo_root / Path(value)

    @property
    def raw_equities_dir(self) -> Path:
        return self.raw_dir / "equities"

    @property
    def raw_fx_dir(self) -> Path:
        return self.raw_dir / "fx"

    @property
    def raw_gold_dir(self) -> Path:
        return self.raw_dir / "gold"

    @property
    def raw_market_snapshots_dir(self) -> Path:
        return self.raw_dir / "market_snapshots"

    @property
    def raw_status_dir(self) -> Path:
        return self.raw_dir / "status"

    @property
    def latest_raw_market_snapshots_path(self) -> Path:
        return self.raw_market_snapshots_dir / "market_snapshot_latest.parquet"

    @property
    def latest_fetch_status_path(self) -> Path:
        return self.raw_status_dir / "fetch_status_latest.parquet"

    @property
    def latest_raw_qa_results_path(self) -> Path:
        return self.raw_status_dir / "qa_results_latest.parquet"

    @property
    def manual_screening_dir(self) -> Path:
        return self.manual_dir / "screening"

    @property
    def manual_screening_store_path(self) -> Path:
        return self.manual_screening_dir / "manual_screening.sqlite3"

    @property
    def manual_holdings_dir(self) -> Path:
        return self.manual_dir / "holdings"

    @property
    def holdings_path(self) -> Path:
        return self.manual_holdings_dir / "holdings.yaml"

    @property
    def intermediate_usd_equities_dir(self) -> Path:
        return self.intermediate_dir / "usd_equities"

    @property
    def intermediate_market_snapshots_dir(self) -> Path:
        return self.intermediate_dir / "market_snapshots"

    @property
    def intermediate_horizon_metrics_dir(self) -> Path:
        return self.intermediate_dir / "horizon_metrics"

    @property
    def intermediate_tool_a_structural_dir(self) -> Path:
        return self.intermediate_dir / "tool_a_structural"

    @property
    def intermediate_tool_a_profiles_dir(self) -> Path:
        return self.intermediate_dir / "tool_a_profiles"

    @property
    def intermediate_tool_b_dir(self) -> Path:
        return self.intermediate_dir / "tool_b"

    @property
    def intermediate_tool_c_dir(self) -> Path:
        return self.intermediate_dir / "tool_c"

    @property
    def intermediate_tool_d_dir(self) -> Path:
        return self.intermediate_dir / "tool_d"

    @property
    def options_features_dir(self) -> Path:
        return self.intermediate_dir / "options_features"

    @property
    def benchmarks_dir(self) -> Path:
        return self.intermediate_dir / "benchmarks"

    @property
    def intermediate_status_dir(self) -> Path:
        return self.intermediate_dir / "status"

    @property
    def latest_normalized_market_snapshots_path(self) -> Path:
        return self.intermediate_market_snapshots_dir / "market_snapshot_latest.parquet"

    @property
    def latest_normalization_qa_results_path(self) -> Path:
        return self.intermediate_status_dir / "normalization_qa_results_latest.parquet"

    @property
    def latest_foundation_manifest_path(self) -> Path:
        return self.intermediate_status_dir / "latest_foundation_manifest.json"

    @property
    def latest_options_manifest_path(self) -> Path:
        return self.intermediate_status_dir / "latest_options_manifest.json"

    @property
    def latest_model_state_manifest_path(self) -> Path:
        return self.intermediate_status_dir / "latest_model_state.json"

    @property
    def output_tool_a_dir(self) -> Path:
        return self.output_dir / "tool_a"

    @property
    def latest_tool_a_snapshot_parquet_path(self) -> Path:
        return self.output_tool_a_dir / "tool_a_latest.parquet"

    @property
    def latest_tool_a_snapshot_csv_path(self) -> Path:
        return self.output_tool_a_dir / "tool_a_latest.csv"

    @property
    def latest_tool_a_structural_metrics_path(self) -> Path:
        return (
            self.intermediate_tool_a_structural_dir / "tool_a_structural_latest.parquet"
        )

    @property
    def output_tool_b_dir(self) -> Path:
        return self.output_dir / "tool_b"

    @property
    def latest_tool_b_snapshot_parquet_path(self) -> Path:
        return self.output_tool_b_dir / "tool_b_latest.parquet"

    @property
    def latest_tool_b_snapshot_csv_path(self) -> Path:
        return self.output_tool_b_dir / "tool_b_latest.csv"

    @property
    def output_tool_c_dir(self) -> Path:
        return self.output_dir / "tool_c"

    @property
    def latest_tool_c_snapshot_parquet_path(self) -> Path:
        return self.output_tool_c_dir / "tool_c_latest.parquet"

    @property
    def latest_tool_c_snapshot_csv_path(self) -> Path:
        return self.output_tool_c_dir / "tool_c_latest.csv"

    @property
    def output_tool_d_dir(self) -> Path:
        return self.output_dir / "tool_d"

    @property
    def output_options_dir(self) -> Path:
        return self.output_dir / "options"

    @property
    def latest_tool_d_snapshot_parquet_path(self) -> Path:
        return self.output_tool_d_dir / "tool_d_latest.parquet"

    @property
    def latest_tool_d_snapshot_csv_path(self) -> Path:
        return self.output_tool_d_dir / "tool_d_latest.csv"

    @property
    def latest_tool_d_spot_snapshot_parquet_path(self) -> Path:
        return self.output_tool_d_dir / "tool_d_latest_spot.parquet"

    @property
    def latest_tool_d_spot_snapshot_csv_path(self) -> Path:
        return self.output_tool_d_dir / "tool_d_latest_spot.csv"

    @property
    def output_combined_dir(self) -> Path:
        return self.output_dir / "combined"

    @property
    def output_hedge_readiness_dir(self) -> Path:
        return self.output_dir / "hedge_readiness"
