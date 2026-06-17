# Phase 1 review record — Capture & Behaviour engine

Date: 2026-06-17
Method: adversarial multi-agent workflow (5 review dimensions — capture-math, honesty-stats,
architecture, tests, edge-integrity — each finding independently verified by a separate agent that
tried to refute it). 27 agents, 22 findings confirmed. Then fixed in the main loop.

## Resolutions

| # | Sev | Finding | Resolution |
|---|---|---|---|
| 1 | HIGH | Anchor-stability gate over-fires: a tiny independent-anchor sample vetoed well-powered archetypes at tercile boundaries (61 cells blanked) | **Demoted the anchor check from a hard abstain to a confidence flag** (`confirmed` / `unconfirmed_disagrees` / `unconfirmed_thin_anchor`). Overlap inflates variance not bias, and effective-N already deflates it, so the all-rows archetype ships, flagged where anchors disagree. OK cells 167→228. New `min_anchor_episodes` config gates whether the cross-check is confirmable. |
| 2,3 (dup), 21, 22 | MED | All-NaN / partial-NaN side: `NaN` capture slipped past the `None`-guards → confident mislabel; raw row count inflated effective-N | `_capture_side` counts only VALID (non-NA) obs for `n_weeks`/effective-N and returns `None` capture on non-finite/zero denominator, reusing `common.numeric.optional_finite_float` (one copy). `_round` also maps non-finite → None. |
| 4 | LOW | `default_capture_horizon` could be off the built horizons → silent empty grounding | `build_and_save` fails loud if it's not in the built horizons. |
| 6 | LOW | Data-grounding not auditable: config cites p33/p67 but `capture_distribution` never emitted them | Added 0.33/0.67 to the emitted quantiles; persisted meta now contains p33=1.611 / p67=2.186 matching the cutoffs 1.61/2.17. |
| 7 | LOW | Dead `buckets` param in `compute_capture_table` (hash/partition could diverge) | Removed the unused param; partition stays the single derived `DOWN_BUCKETS`/`UP_BUCKETS`. |
| 5 | NIT | Cutoffs grounded on full 65 vs floor-eligible (~identical for OK pop) | Noted; no change (verifier: OK-pop p33=1.6117 ≈ all-rows 1.6109). |
| 8–20 | MED/LOW | Test-coverage gaps (no `build_and_save` I/O test, effective-N floor only tested at the degenerate zero-rows path, no horizon-deflation / `gold_flat` exclusion / `THIN_BOTH` / no-anchor / component-mean / NaN tests, shallow distribution + hash tests) | **Tests expanded 10 → 30**, including the `build_and_save` persist/meta path, real floor at h>1, horizon deflation, gold_flat exclusion, THIN_BOTH, NaN abstain, and config-hash sensitivity (spine + buckets + thresholds). |

## Outcome
- Archetype spread (OK cells): HEDGE 74 / TORQUE 70 / DEAD_WEIGHT 71 / CONVEX 13; confidence:
  confirmed 164 / unconfirmed_disagrees 58 / unconfirmed_thin_anchor 6.
- ruff clean; full suite **1348 passed**.
