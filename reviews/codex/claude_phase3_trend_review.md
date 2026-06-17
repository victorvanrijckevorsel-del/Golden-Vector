# Phase 3 review record — behaviour-change (trend) layer

Date: 2026-06-17
Method: adversarial multi-agent workflow (4 dimensions — trend-math, significance, architecture,
tests — each finding independently verified). 24 agents, 19 confirmed findings (1 HIGH, several
MEDIUM, rest LOW/NIT; many were test-coverage gaps).

## Resolutions

| # | Sev | Finding | Resolution |
|---|---|---|---|
| 1 | HIGH | Behaviour artifacts published file-by-file (8 writes), not all-or-nothing with a key guard | Added shared `common.parquet.write_run_stamped_set` (all stamped first, then all latest, missing/extra-key guard); `build_and_save` publishes the 4-artifact set through it (`BEHAVIOR_ARTIFACT_SPECS`), meta written last; `conditional_dial.write_dial_artifacts` refactored to delegate (one copy). |
| 2 | MEDIUM | Alpha (leading) label blanked by the BEAT recent/older split floors → the indicator meant to lead is suppressed by what it leads | Alpha label now gates on its OWN power (`na >= min_anchors` + slope present), independent of the beat status. Live effect: alpha movers 86→121, alpha-INSUFFICIENT 1318→896. |
| 3 | MEDIUM/LOW | NaN in anchor beats inflated effective N and yielded a NaN delta with status OK; numpy vs pandas mean inconsistency | Drop NA anchor beats ONCE (like the capture side); window means via `optional_finite_float`; `trend_p_value` guarded. NaN anchors now reduce the count instead of poisoning the cell. |
| 4 | LOW | `behavior_config_hash` stamped `DIAL_SCHEMA_VERSION` without verifying the on-disk spine | `build_and_save` reads `dial_meta.json` and fails loud if the spine schema_version != expected (skipped only for fixture spines with no meta). |
| 5 | LOW/NIT (×3) | `recent_prior_min_pool_effective_n` gates a ticker COUNT but is named `*_effective_n` | Renamed to `recent_prior_min_pool_tickers` (config + yaml + engine + tests) with an accurate comment. |
| 6 | NIT | `_loo_prior` / `_window_prior` duplicated the LOO averaging | Factored a single `_loo_mean(means, ticker)` core; both call it. |
| 7 | LOW/NIT | Alpha uses raw MK p (no FDR); decay shrinks toward the all-history prior | Documented in `TREND_CAVEAT` (alpha is a raw, uncorrected leading indicator); decay-toward-all-history is by-design (descriptive, never feeds the gate). |
| 8 | HIGH | FDR *suppression* never tested (every family m=1) | Added `test_fdr_suppresses_borderline_movers_in_a_family` (1 mover + 4 borderline + 26 flat → borderline raw-significant but q>q_fdr → STABLE; mover survives). |
| 9 | MEDIUM | MK sign-disagreement gate untested | Added `test_beat_label_requires_mk_sign_agreement` (sign-disagree / tau==0 / q>q_fdr / |delta|<thr all → STABLE). |
| 10 | MEDIUM | anchors-only windows + h>1 deflation untested (all fixtures h=1, 100% anchors) | Added `test_windows_use_anchors_only_and_deflate_by_horizon` (mixed anchors at h=4; windows ignore non-anchors; all_effective_n = rows/h). |
| 11 | LOW (×4) | decay / alpha-improving-stable-insufficient / mde / peer-vs-own-past / stats edges untested | Added decay, alpha-branch, mde, a discriminating peer-shrinkage test (peers beat ~always so the peer-pull lands above 0.5 — impossible under own-past), and stats edge tests (partial-tie MK var, decay NaN filter, two_proportion_p symmetry, BH all-NaN). |

## Outcome
- Beat trend: 3 movers / 629 STABLE / 1318 INSUFFICIENT (honest abstention preserved).
- Alpha trend: 121 movers (61 improving / 60 deteriorating) — leading indicator now surfaced on its
  own power.
- ruff clean; behaviour+stats+config+lab tests green (full suite gating before commit).
