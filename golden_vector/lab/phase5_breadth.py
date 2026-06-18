"""Phase 5 acceptance-bar freeze: effective breadth (N_eff) -> required IC floor.

A ONE-OFF, deterministic, auditable computation run BEFORE the Phase 5 backtest is
frozen (spec section 4). N_eff is a property of the residual-return covariance, not of
any forward label, so measuring it leaks nothing — but the inputs are pinned (a frozen
pre-window) so the number cannot be re-tuned after results are seen.

Residual return for name i, week w (over the pre-window, balanced block):
    resid_iw = stock_log_ret_iw  -  beta_i * gdx_log_ret_w
with beta_i a single OLS slope over the block (the common-GDX-factor removed so the
correlation matrix reflects idiosyncratic co-movement). N_eff = participation ratio of
the Ledoit-Wolf-shrunk residual correlation. required_ic_floor solves
IR_ceiling = IC * sqrt(N_eff) * transfer = target_ir.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from golden_vector.features.weekly_returns import build_weekly_return_frame
from golden_vector.lab.statistics import effective_breadth

# Frozen pre-registration inputs (spec section 4).
PRE_WINDOW_ASOF = "2024-12-27"  # W-FRI Friday; weeks ending after this are unseen
BLOCK_WEEKS = 260  # balanced 5-year block ending at the as-of (clean, PSD panel)
TARGET_IR = 0.3
TRANSFER = 0.5


def _week_end(week_period: str) -> pd.Timestamp:
    return pd.Timestamp(str(week_period).split("/")[-1])


def compute_phase5_breadth(
    paths,
    *,
    as_of: str = PRE_WINDOW_ASOF,
    block_weeks: int = BLOCK_WEEKS,
    target_ir: float = TARGET_IR,
    transfer: float = TRANSFER,
) -> dict[str, float]:
    """Reconstruct residual returns over the frozen pre-window and return the breadth
    summary plus the derived ``required_ic_floor``."""

    gold_candidates = sorted(paths.raw_gold_dir.glob("*.parquet"))
    if not gold_candidates:
        raise FileNotFoundError(f"No raw gold parquet in {paths.raw_gold_dir}")
    gold = pd.read_parquet(gold_candidates[0])
    equities = {
        path.stem: pd.read_parquet(path)
        for path in sorted(paths.intermediate_usd_equities_dir.glob("*.parquet"))
    }
    benchmarks = {
        ticker: pd.read_parquet(paths.benchmarks_dir / f"{ticker}.parquet")
        for ticker in ("GDX", "GDXJ")
        if (paths.benchmarks_dir / f"{ticker}.parquet").exists()
    }
    weekly = build_weekly_return_frame(
        normalized_equity_histories=equities,
        gold_history=gold,
        benchmark_histories=benchmarks,
    )
    weekly = weekly[weekly["gdx_log_ret"].notna()].copy()
    # Frozen pre-window: keep only weeks ending on/before the as-of Friday.
    asof = pd.Timestamp(as_of)
    weekly = weekly[weekly["week_period"].map(_week_end) <= asof]

    stock = weekly.pivot_table(index="week_period", values="stock_log_ret", columns="ticker")
    gdx = weekly.drop_duplicates("week_period").set_index("week_period")["gdx_log_ret"]
    gdx = pd.to_numeric(gdx, errors="coerce").reindex(stock.index)
    stock = stock.sort_index()
    gdx = gdx.sort_index()

    # Balanced block: the last `block_weeks` weeks, names complete across the block.
    block = stock.tail(block_weeks)
    gdx_block = gdx.tail(block_weeks)
    keep_weeks = gdx_block.notna()
    block = block.loc[keep_weeks.values]
    gdx_block = gdx_block.loc[keep_weeks.values]
    block = block.dropna(axis=1, how="any")  # names complete over the whole block
    if block.shape[1] < 2 or block.shape[0] < 2:
        raise ValueError(f"balanced block too small: {block.shape}")

    g = gdx_block.to_numpy(dtype=float)
    g_var = float(np.var(g))
    resid = np.empty(block.shape, dtype=float)
    for j, ticker in enumerate(block.columns):
        s = block[ticker].to_numpy(dtype=float)
        beta = float(np.cov(s, g, bias=True)[0, 1] / g_var) if g_var > 0 else 0.0
        resid[:, j] = s - beta * g

    breadth = effective_breadth(resid)
    n_eff = breadth["n_eff_shrunk"]
    required_ic = target_ir / (transfer * np.sqrt(n_eff)) if n_eff > 0 else float("inf")
    return {
        **breadth,
        "as_of": as_of,
        "block_weeks_used": float(block.shape[0]),
        "names_used": float(block.shape[1]),
        "target_ir": target_ir,
        "transfer": transfer,
        "required_ic_floor": float(required_ic),
    }


def main() -> None:
    from golden_vector.app.paths import ProjectPaths

    r = compute_phase5_breadth(ProjectPaths.discover())
    print("Phase 5 breadth freeze (pre-window as-of", r["as_of"], "):")
    print(f"  names used         : {int(r['names_used'])}")
    print(f"  weeks used (block) : {int(r['block_weeks_used'])}")
    print(f"  avg residual corr  : {r['avg_correlation']:.4f}")
    print(f"  LW shrinkage       : {r['shrinkage_intensity']:.4f}")
    print(f"  N_eff (sample)     : {r['n_eff_sample']:.3f}")
    print(f"  N_eff (shrunk)     : {r['n_eff_shrunk']:.3f}")
    print(f"  target IR / transfer: {r['target_ir']} / {r['transfer']}")
    print(f"  => required_ic_floor: {r['required_ic_floor']:.4f}")


if __name__ == "__main__":
    main()
