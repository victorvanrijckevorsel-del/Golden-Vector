from datetime import date

import pandas as pd
import pytest

from golden_vector.contracts.config_models import ToolCConfig
from golden_vector.model.tool_c import (
    TOOL_C_OUTPUT_COLUMNS,
    build_tool_c_output_frame,
)


def test_build_tool_c_output_frame_produces_symmetric_ranks():
    tool_a = pd.DataFrame(
        [
            _tool_a_row("AAA", down_beta=2.0, up_beta=0.6, score_eligible=True),
            _tool_a_row("BBB", down_beta=1.0, up_beta=2.0, score_eligible=True),
            _tool_a_row("CCC", down_beta=3.0, up_beta=3.0, score_eligible=False),
        ]
    )
    metrics = pd.DataFrame(
        [
            _metric_row(
                "AAA",
                rel_weakness=1.0,
                rel_strength=0.2,
                downside_hit_rate=1.0,
                upside_hit_rate=0.0,
            ),
            _metric_row(
                "BBB",
                rel_weakness=0.2,
                rel_strength=1.0,
                downside_hit_rate=0.0,
                upside_hit_rate=1.0,
            ),
            _metric_row(
                "CCC",
                rel_weakness=1.0,
                rel_strength=1.0,
                downside_hit_rate=1.0,
                upside_hit_rate=1.0,
            ),
        ]
    )

    output = build_tool_c_output_frame(
        tool_a_latest=tool_a,
        relative_metrics=metrics,
        config=ToolCConfig(min_events=2),
        source_run_id="tool-c-run",
    )
    rows = output.set_index("ticker")

    assert list(output.columns) == TOOL_C_OUTPUT_COLUMNS
    assert rows.loc["AAA", "tool_c_downside_rank"] == 100.0
    assert rows.loc["AAA", "tool_c_downside_score"] == 100.0
    assert rows.loc["BBB", "tool_c_upside_rank"] == 100.0
    assert rows.loc["BBB", "tool_c_upside_score"] == 100.0
    assert pd.isna(rows.loc["CCC", "tool_c_downside_rank"])
    assert pd.isna(rows.loc["CCC", "tool_c_upside_rank"])
    assert "score_ineligible" in rows.loc["CCC", "tool_c_downside_tags"]
    assert rows.loc["AAA", "source_run_id"] == "tool-c-run"
    assert rows.loc["AAA", "source_tool_a_run_id"] == "tool-a-run"


def test_tool_c_thin_relative_metric_is_tagged_and_excluded_from_rank():
    tool_a = pd.DataFrame(
        [
            _tool_a_row("AAA", down_beta=2.0, up_beta=1.0, score_eligible=True),
            _tool_a_row("BBB", down_beta=1.0, up_beta=0.9, score_eligible=True),
        ]
    )
    metrics = pd.DataFrame(
        [
            _metric_row("AAA", rel_weakness=None, rel_strength=0.6, downside_hit_rate=0.5),
            _metric_row("BBB", rel_weakness=0.1, rel_strength=0.4, downside_hit_rate=0.2),
        ]
    )
    metrics.loc[metrics["ticker"] == "AAA", "rel_weakness_vs_gold_n"] = 1

    output = build_tool_c_output_frame(
        tool_a_latest=tool_a,
        relative_metrics=metrics,
        config=ToolCConfig(min_events=2),
        source_run_id="tool-c-run",
    )
    row = output.set_index("ticker").loc["AAA"]

    assert pd.notna(row["tool_c_downside_rank"])
    assert "thin_history" in row["tool_c_downside_tags"]


def test_tool_c_missing_score_eligible_column_fails_loud():
    tool_a = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "as_of_date": date(2026, 6, 1),
                "source_run_id": "tool-a-run",
                "down_beta_core": 2.0,
                "up_beta_core": 1.0,
                "downside_volatility_52w": 0.5,
                "confidence_score": 0.9,
            }
        ]
    )
    metrics = pd.DataFrame(
        [_metric_row("AAA", rel_weakness=0.7, rel_strength=0.4)]
    )

    # Fail loud, never open: defaulting True would silently rank every
    # degraded ticker if Tool A ever dropped/renamed the column.
    with pytest.raises(ValueError, match="score_eligible"):
        build_tool_c_output_frame(
            tool_a_latest=tool_a,
            relative_metrics=metrics,
            config=ToolCConfig(min_events=2),
            source_run_id="tool-c-run",
        )


def test_tool_c_tail_counts_contribute_to_thin_history_tags():
    tool_a = pd.DataFrame(
        [_tool_a_row("AAA", down_beta=2.0, up_beta=1.0, score_eligible=True)]
    )
    metrics = pd.DataFrame(
        [_metric_row("AAA", rel_weakness=0.7, rel_strength=0.4)]
    )
    metrics.loc[0, "tail_avg_return_worst10pct"] = None
    metrics.loc[0, "tail_avg_return_worst10pct_n"] = 1

    output = build_tool_c_output_frame(
        tool_a_latest=tool_a,
        relative_metrics=metrics,
        config=ToolCConfig(min_events=2),
        source_run_id="tool-c-run",
    )

    assert "thin_history" in output.iloc[0]["tool_c_downside_tags"]


def _tool_a_row(
    ticker: str,
    *,
    down_beta: float,
    up_beta: float,
    score_eligible: bool,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "as_of_date": date(2026, 6, 1),
        "source_run_id": "tool-a-run",
        "snapshot_refresh_run_id": "refresh-run",
        "down_beta_core": down_beta,
        "up_beta_core": up_beta,
        "asymmetry_ratio_core": down_beta / up_beta,
        "downside_volatility_52w": down_beta / 4.0,
        "confidence_score": 0.9,
        "score_eligible": score_eligible,
    }


def _metric_row(
    ticker: str,
    *,
    rel_weakness: float | None,
    rel_strength: float,
    downside_hit_rate: float = 0.5,
    upside_hit_rate: float = 0.5,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "rel_weakness_vs_gold_pct": rel_weakness,
        "rel_weakness_vs_gold_n": 3,
        "rel_weakness_vs_gdx_pct": rel_weakness,
        "rel_weakness_vs_gdx_n": 3,
        "rel_weakness_vs_gdxj_pct": rel_weakness,
        "rel_weakness_vs_gdxj_n": 3,
        "rel_strength_vs_gold_pct": rel_strength,
        "rel_strength_vs_gold_n": 3,
        "rel_strength_vs_gdx_pct": rel_strength,
        "rel_strength_vs_gdx_n": 3,
        "rel_strength_vs_gdxj_pct": rel_strength,
        "rel_strength_vs_gdxj_n": 3,
        "n_weeks_gold": 12,
        "n_weeks_gdx": 12,
        "n_weeks_gdxj": 12,
        "downside_hit_rate_10pct": downside_hit_rate,
        "downside_hit_rate_n": 3,
        "upside_hit_rate_10pct": upside_hit_rate,
        "upside_hit_rate_n": 3,
        "tail_avg_return_worst10pct": -0.10,
        "tail_avg_return_worst10pct_n": 3,
        "tail_avg_return_worst20pct": -0.08,
        "tail_avg_return_worst20pct_n": 3,
        "tail_avg_return_best10pct": 0.10,
        "tail_avg_return_best10pct_n": 3,
        "tail_avg_return_best20pct": 0.08,
        "tail_avg_return_best20pct_n": 3,
    }
