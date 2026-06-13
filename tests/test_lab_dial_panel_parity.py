"""Golden parity gate for the dial -> shared-panel refactor (plan_v3 HIGH-1).

The dial used to compute its own forward alpha (a private fork of the math in
``forward_returns.build_forward_return_panel``). The refactor makes the dial
CONSUME that panel so the chart's alpha and the table's alpha are one column.
This gate proves the refactor changed NOTHING in the shipped GDX-13w output:

- ``dial_golden_13w.parquet`` was generated from the PRE-refactor code on the
  deterministic frame below; the test rebuilds and asserts byte-identical output
  across every public column.
- A second test asserts the dial's episode alpha now equals the shared panel's
  ``fwd_alpha_gdx_13w`` exactly (no forked math can survive).

Regenerate the golden ONLY intentionally (a deliberate, reviewed output change):
    python -m tests.tools.regen_dial_golden
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from golden_vector.lab.conditional_dial import build_dial_table

GOLDEN_PATH = Path(__file__).parent / "fixtures" / "lab" / "dial_golden_13w.parquet"
PARITY_HORIZON = 13
PARITY_MIN_EFF_N = 2.0


def parity_weekly_frame() -> pd.DataFrame:
    """Deterministic weekly frame exercising all five gold buckets + mixed beats.

    Gold runs in 30-week blocks cycling through weekly levels chosen so the
    forward-13w gold return lands in down_big / down / flat / up / up_big in
    turn; repeated to give ~60 weeks per bucket. Stock returns carry a per-ticker
    edge plus a deterministic sinusoid so alpha vs GDX flips sign within a bucket
    (non-trivial p_beat, Wilson, shrinkage). No randomness -> stable golden.
    """

    n = 300
    grid = [str(p) for p in pd.period_range("2010-01-08", periods=n, freq="W-FRI")]
    block_levels = [-0.018, -0.008, 0.0, 0.008, 0.018]  # -> ~ -0.21/-0.10/0/+0.11/+0.26 fwd
    gold = np.array(
        [block_levels[(i // 30) % len(block_levels)] for i in range(n)],
        dtype=float,
    )
    tickers = (
        ("AAA", 0.003, 0.0),
        ("BBB", -0.003, 1.0),
        ("CCC", 0.001, 2.0),
        ("DDD", -0.001, 3.0),
        ("EEE", 0.002, 4.0),
        ("FFF", -0.002, 5.0),
    )
    rows: list[dict[str, object]] = []
    for ticker, edge, phase in tickers:
        for i in range(n):
            stock = 0.001 + edge + 0.012 * np.sin(0.3 * i + phase)
            rows.append(
                {
                    "ticker": ticker,
                    "week_period": grid[i],
                    "stock_log_ret": float(stock),
                    "gold_log_ret": float(gold[i]),
                    "gdx_log_ret": 0.001,
                    "gdxj_log_ret": 0.0008,
                }
            )
    return pd.DataFrame(rows)


def test_dial_table_gdx_13w_output_preserved_against_golden() -> None:
    """The shipped GDX-13w table is byte-identical after the panel refactor."""

    assert GOLDEN_PATH.exists(), (
        f"Missing golden fixture {GOLDEN_PATH}; generate it from the pre-refactor "
        "code with tests/tools/regen_dial_golden.py."
    )
    rebuilt = build_dial_table(
        parity_weekly_frame(),
        horizon_weeks=PARITY_HORIZON,
        min_effective_n=PARITY_MIN_EFF_N,
    ).reset_index(drop=True)
    golden = pd.read_parquet(GOLDEN_PATH).reset_index(drop=True)
    assert list(rebuilt.columns) == list(golden.columns), (
        f"column drift: {list(rebuilt.columns)} vs {list(golden.columns)}"
    )
    pd.testing.assert_frame_equal(rebuilt, golden, check_dtype=False, check_like=False)


def test_dial_episode_alpha_comes_from_shared_panel() -> None:
    """No forked alpha math survives: dial alpha == panel fwd_alpha_gdx_13w."""

    from golden_vector.lab.conditional_dial import build_episode_frame
    from golden_vector.lab.forward_returns import build_forward_return_panel

    frame = parity_weekly_frame()
    episodes = build_episode_frame(frame, horizon_weeks=PARITY_HORIZON, benchmark="GDX")
    panel = build_forward_return_panel(frame, horizons_weeks=[PARITY_HORIZON])
    merged = episodes.merge(
        panel[["ticker", "week_period", "fwd_alpha_gdx_13w"]],
        on=["ticker", "week_period"],
        how="left",
    )
    assert not merged.empty
    assert merged["fwd_alpha_gdx_13w"].notna().all(), "episode without a panel alpha"
    diff = (
        merged["alpha"].astype(float) - merged["fwd_alpha_gdx_13w"].astype(float)
    ).abs()
    assert float(diff.max()) < 1e-12
