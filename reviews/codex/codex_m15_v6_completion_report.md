# M1.5 v6 Completion Report

**Status:** CHECKPOINT C complete
**Branch:** `dev-vic`
**Latest commit before Step 9 docs:** `e091ed2 m15 v6 audit fixes`
**Date:** 2026-06-02

## Final Scope

M1.5 v6 completes the Hedge Readiness CLI report as the downside-product action layer. It now supports:

- universe sensitivity ranking by Tool A `down_beta_core`
- strategy-generic option scenario math, with long-put scenarios surfaced in the report
- portfolio totals for share and dollar-exposure holdings
- held-position scenario tables
- universe-level speculation candidates
- cross-ticker comparison table
- proxy hedges for held non-optionable tickers
- CLI flags for ranking, comparison, caps, and scenario quantity
- docs and manual smoke evidence

## File Changes And Line Counts

Diff summary from the v6 baseline (`a37a013`) through Step 9:

```text
28 files changed, 3578 insertions(+), 497 deletions(-)
```

Largest touched areas:

| Area | Main files |
|---|---|
| Report wiring | `golden_vector/hedge/report.py`, `golden_vector/cli.py` |
| Scenario/math | `golden_vector/features/black_scholes.py`, `golden_vector/hedge/scenarios.py` |
| Ranking/totals | `golden_vector/hedge/sensitivity_ranking.py`, `golden_vector/hedge/portfolio_totals.py` |
| Shared helpers/hardening | `golden_vector/hedge/_helpers.py`, `golden_vector/features/options_chain.py` |
| Existing M1 cleanups | `golden_vector/hedge/proxy_hedge.py`, `golden_vector/ingestion/options_phase.py` |
| Tests | `tests/test_*hedge*`, `tests/test_strategy_generic_math.py`, `tests/test_hedge_data_contracts.py` |
| Docs/progress | `docs/hedge_readiness.md`, `reviews/codex/codex_m15_v6_progress.md` |

## HedgeReadinessSections Shape

`golden_vector/hedge/report.py` defines the reusable section object for the markdown emitter and future UI work:

```python
@dataclass(frozen=True)
class HedgeReadinessSections:
    header: HeaderContext
    summary: SnapshotSummaryData
    sensitivity_ranking: SensitivityRankingData
    portfolio_totals: PortfolioTotalsData | None
    held_positions: HeldPositionsData | None
    speculation_candidates: SpeculationCandidatesData
    comparison: ComparisonViewData
    proxy_hedges: ProxyHedgesData | None
    sources: SourcesData
```

This includes both `header` and `sources`, which were missing from the v5 plan shape. M2 can
consume this object without re-parsing markdown.

## Manual Smoke Reports

### Empty Holdings

Command:

```powershell
python main.py hedge-readiness --ranking-sort-by down_beta_core --comparison-sort-by pnl_per_dollar_premium_minus10 --ranking-max-tickers 5 --speculation-max-tickers 3 --quantity 10
```

Output:

```text
Hedge readiness report written: data/output/hedge_readiness/20260601_20260602T174323Z-hedge-readiness-6a6079a4.md
Summary: 21 directly hedgeable, 1 thin, 38 no listed options, 0 holdings.
Context alignment: WARN - Tool A snapshot refresh does not match options source run; Tool B snapshot refresh does not match options source run.
```

Sections rendered:

```text
Snapshot Summary
Sensitivity Ranking
Speculation Candidates
Cross-ticker Comparison View
Sources / Run Summary
```

Portfolio-only sections were skipped gracefully because holdings were empty.

### Mixed Two-position Holdings

Temporary fixture used for smoke:

```yaml
version: 1
holdings:
  - ticker: AEM
    shares: 200
  - ticker: AAUC.TO
    dollar_exposure: 5000
```

Command:

```powershell
python main.py hedge-readiness --ranking-sort-by down_beta_core --comparison-sort-by pnl_per_dollar_premium_minus10 --ranking-max-tickers 5 --speculation-max-tickers 3 --quantity 10
```

Output:

```text
Hedge readiness report written: data/output/hedge_readiness/20260601_20260602T174325Z-hedge-readiness-ce5ea889.md
Summary: 21 directly hedgeable, 1 thin, 38 no listed options, 2 holdings.
Context alignment: WARN - Tool A snapshot refresh does not match options source run; Tool B snapshot refresh does not match options source run.
```

Sections rendered:

```text
Snapshot Summary
Sensitivity Ranking
Portfolio Totals
Held Positions
Speculation Candidates
Cross-ticker Comparison View
Proxy Hedges
Sources / Run Summary
```

Together with the title header, this confirms the intended 9-section order. The command also
demonstrated all 5 CLI flags, including `--quantity 10` and `--ranking-max-tickers 5`.

The original `data/manual/holdings/holdings.yaml` content was restored after the smoke run and was not committed.

## Verification

Passed during the final audit fix pass:

```text
Focused hedge/options tests: 75 passed
Full suite: 519 passed
python -m py_compile: passed for touched runtime files
git diff --check: passed
```

Passed during Step 9 final verification:

```text
python -m pytest -q: 519 passed
```

## v5 Findings Closure

| Finding | Resolution |
|---|---|
| Header and Sources missing from section object | Fixed. `HedgeReadinessSections` includes `header` and `sources`. |
| 8 vs 9 section contradiction | Fixed in implementation and docs. Report order is 9 sections including header and sources. |
| Dollar-exposure hedge-cost contradiction | Fixed with current-price-based share economics. |
| `breakeven_gold_pct` sort direction | Fixed earlier: breakeven sorting is closest-to-zero-first for valid negative values. |
| Drifted step references | v6 was re-baselined; progress log records actual steps and commits. |
| Stale CLI/config counts | Fixed in implementation: 5 CLI flags and the v6 config fields are wired and documented. |
| Duplicate `PortfolioTotalsData` definitions | Fixed by implementing one runtime `PortfolioTotalsData` in `portfolio_totals.py`. |
| Options isolation double-count risk | Fixed in `options_phase.py`; tests cover per-ticker isolation and summary counts. |
| `_helpers.py` migration vs header-context wording | Fixed as a no-behavior helper consolidation. |

## CODE_REVIEW M1 Closure

| Item | Resolution |
|---|---|
| H1 IV sort direction | Folded into M1 punch-list baseline; speculation now selects cheap-IV candidates first. |
| H2 proxy basis-risk tiers | Folded into M1 punch-list baseline with 3-tier basis-risk behavior and config coverage. |
| H3 options per-ticker isolation | Folded into M1 punch-list baseline; one ticker failure does not collapse the phase. |
| M1 sign convention | Scenario math uses explicit gold-down moves and long-put P&L rules. |
| M2 breakeven sort | Covered in comparison tests; closest-to-zero valid negative breakevens sort first. |
| M3 helper duplication | `_helpers.py` consolidates shared row/float/ticker helpers. |
| M4 same-day feature-row dedup | Folded into M1 punch-list baseline and options-phase tests. |
| M5 hidden risk-free fallback | Fixed and surfaced where current prices depend on it. |

## Self-review And Claude Audit Closure

| Review pass | Resolution |
|---|---|
| Checkpoint A Claude review | Config, skip-reason, hedge-cost, dead-input, sentinel, and dedup issues fixed. |
| Batch 3 self-review | Report section builder/emitter shape verified; r=0 fallback and threshold threading checked. |
| Deep review after Checkpoint B | Fixed threshold, cap, proxy-count, formatting, note, and price-source issues. |
| Holistic first-part review | Fixed stale features, optionability normalization, chain keys, and P&L wording. |
| Claude M1.5 audit | Fixed risk-free delta fallback, contracts, straddle guard, and latest-row sorting. |

## Deviations

- The plan guidance says "10 steps -> 10 commits", but the v6 step table and checkpoint text
  define real implementation through Step 9. The implementation followed the step table.
- The report title is the `# Hedge Readiness Report` header; the remaining section headings are
  `##` headings. The smoke heading scan therefore shows 8 `##` headings for the mixed report plus
  the title header, matching the intended 9-section report.
- Two product choices remain unchanged because Claude marked them as requiring explicit user direction:
  - `score_eligible=False` still sinks a ticker in Sensitivity Ranking.
  - the 300% maximum implied-volatility ceiling remains in the tradability gate.

## Open Questions

1. Should Sensitivity Ranking rank tickers with `score_eligible=False` when `down_beta_core` exists, adding a note instead of sinking them?
2. Should the speculative put workflow raise or remove the 300% implied-volatility ceiling for deep-OTM tail puts?
3. The current local data still reports context alignment `WARN` because Tool A and Tool B
   snapshots do not match the latest options source run. That is correctly surfaced, but the
   analytical snapshots should be refreshed before user-facing decisions.
