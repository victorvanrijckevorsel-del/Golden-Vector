# Plan review — rebased gold/stock/GDX/GDXJ overlay (detail page), against the house rules

## Goal
Replace the abstract "Rolling Structural Delta" (beta) chart on `/ticker/<t>` with a
**rebased-to-100 overlay**: gold, the stock, GDX, GDXJ — all indexed to 100 at the start of
the selected lookback (6M / 1Y / 3Y), so you can SEE whether the miner beats gold AND the
gold-miner ETFs. The beta NUMBERS stay in the windowed table above the chart (nothing lost).
(A prior rebased gold overlay was removed for sharing the beta y-axis — uninterpretable. This
is a STANDALONE all-rebased chart: every line shares one honest % unit, so that problem is gone.)

## Rule check (the things Victor called out)
- **Backend computes, serve renders.** The rebasing math (value/base*100) and the series
  assembly live in the BACKEND: a one-line primitive `rebase_to_base` in `common/numeric.py`
  + an assembler `build_rebased_comparison_series` in `model/structural.py`. Serve (`charts.py`)
  only maps the pre-computed values to SVG pixels (rendering geometry, like the existing chart
  builders) — NO business arithmetic in serve.
- **One copy of everything (reuse, don't fork).** Reuse:
  - `model/structural.build_structural_weekly_series` — already produces `stock_basis_usd` +
    `gold_basis_usd`, and `workspace_state` ALREADY calls it for this page (line 216). Stock +
    gold prices are already in hand — zero new loading for them.
  - the benchmark path (`_read_cached_benchmark_history` → `normalize_equity_history_to_usd` →
    `build_structural_history_frames`) for GDX/GDXJ weekly prices. To avoid a second copy of that
    inline loading (currently inside `benchmark_betas.build_benchmark_betas_frame`), EXTRACT it
    once into `load_benchmark_weekly_series(paths, app_config, gold_history)` and have BOTH
    benchmark_betas and the detail page call it.
  - `workspace_state._WINDOW_WEEKS` (6M=26/12M=52/3Y=156) for the lookback length + the existing
    window-toggle UI (the toggle now selects the lookback, all 4 series always shown).
  - the chart SVG primitive. `_build_beta_history_svg` is per-window (toggle lines) and is called
    ONLY by the chart we're replacing → it becomes dead. Replace it with one focused
    `_build_multiline_overlay_svg(series_by_label, colors, y_label)` (all lines visible, shared
    y-axis, legend) and DELETE the dead `_build_beta_history_svg` (no duplication, no dead code).
- **Simplest thing that works.** No new persisted artifact: the detail page already computes the
  weekly series at serve time (established pattern for this interactive page), so we reuse that
  path + add GDX/GDXJ the same way. No new config, no new pipeline stage.
- **Fail loud on required / degrade per-item on optional.** Gold + stock are required (chart's
  reason to exist) — keep the existing missing/corrupt/no-data states. GDX/GDXJ are OPTIONAL: a
  missing/unreadable benchmark history greys out that one line (or omits it), the chart still
  renders. Never abort the page on a missing ETF.
- **Label the basis.** Title + caption state "indexed to 100 at the start of the <window> window;
  USD." Each line labeled (gold / <ticker> / GDX / GDXJ).
- **Tests prove behavior.** Unit: `rebase_to_base` (first point = 100, proportional, handles
  empty/NaN). Unit: `build_rebased_comparison_series` (window slice + per-series rebase +
  missing-series degrade). Render: the panel shows the 4 labels + rebased values; a missing-GDXJ
  case still renders the other 3.

## Files
- `golden_vector/common/numeric.py` — `rebase_to_base`.
- `golden_vector/model/structural.py` — `build_rebased_comparison_series`.
- `golden_vector/portfolio/benchmark_betas.py` — extract `load_benchmark_weekly_series` (reused).
- `golden_vector/serve/workspace_state.py` — load GDX/GDXJ weekly + assemble rebased series into
  `ToolADetailState` (new field); reuse `_WINDOW_WEEKS`.
- `golden_vector/serve/charts.py` — `_build_multiline_overlay_svg`; remove `_build_beta_history_svg`.
- `golden_vector/serve/detail_panels.py` — `_render_rolling_structural_delta` → rebased overlay,
  same safety states.
- tests: `test_numeric` (rebase), `test_structural` (assembler), `test_workspace_app`/detail render.

## Verdict
Centralized, reuses 5 existing helpers, adds 1 primitive + 1 assembler + 1 SVG builder, removes
1 dead builder. No duplication, no new artifact, no serve-side business math. Proceed to build.
