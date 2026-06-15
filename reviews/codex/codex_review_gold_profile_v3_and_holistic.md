# Gold-Profile Dashboard v3 + Holistic Review

Date: 2026-06-15
Branch reviewed: `dev-vic`
HEAD reviewed: `5b4ba70`

## Verdicts

Part A - v3 basis fix: APPROVE WITH CHANGES

The v3 fix is real: episodes now persist `alpha_simple`, the distribution strip plots ticks from `alpha_simple`, the marker uses the persisted simple-return median, schema version moved to 3, and v2 artifacts go stale. I did not find evidence that the basis fix broke the legacy `build_episode_frame` parity path. One small honesty issue remains around the defensive clamp: the marker can be pinned to an edge while aria/text still says only `median X%`.

Part B - holistic integrated page: NEEDS CHANGES

The page is much better than the pre-v3 surface, but the full drill-down is not yet one fully coherent, architecture-grade surface. Two issues matter: the collapsed dots chart still plots and labels log-return alpha while the headline/strip/profile/overview are now simple-return based, and the lab artifacts are not read through one atomic artifact pointer even though the meta already records run-stamped artifacts. These are not syntax bugs; they are consistency and data-spine issues that will confuse users or make stale/mixed artifact states possible.

## Checks Run

- `python -m pytest tests/test_lab_curve.py tests/test_lab_page.py tests/test_lab_gold_profile.py tests/test_lab_dial_panel_parity.py -q`
- Result: `86 passed in 96.27s`

Live spot checks:

- `/lab/dial/PRU?scenario=gold_down&horizon=13&benchmark=GDX`
- `/lab/dial/PRU?scenario=gold_down&horizon=13&benchmark=GDXJ`
- `/lab/dial/KGC?scenario=gold_down&horizon=13&benchmark=GDX`
- `/lab/dial/AAUC.TO?scenario=gold_down&horizon=13&benchmark=GDX` as a thin-data case

Artifact checks:

- `data/lab/dial_meta.json` is schema version 3.
- `dial_episodes_latest.parquet` contains `alpha_simple`.
- `dial_profile_latest.parquet` contains 520 rows; label status split observed: 330 `OK`, 190 `INSUFFICIENT_CROSS_SCENARIO_HISTORY`.
- PRU/GDX gold-down distribution: 158 scenario rows, raw beat-rate 90.5%, persisted median simple alpha about +24.8%, simple tick range about -47.3% to +94.2%.

## Findings

| Severity | Scope | File:line | What is wrong | Why it matters | Fix |
|---|---|---:|---|---|---|
| MEDIUM | B | `golden_vector/serve/lab_curve_data.py:319`, `golden_vector/serve/lab_curve_data.py:320`, `golden_vector/serve/lab_curve_page.py:450`, `golden_vector/serve/lab_curve_page.py:551`, `golden_vector/serve/lab_curve_page.py:610`, `golden_vector/serve/lab_curve_page.py:617`, `golden_vector/serve/lab_curve_page.py:627` | The drill-down still uses two percentage bases on one page. The distribution strip uses simple-return alpha (`alpha_simple`), but the collapsed dots chart still scales and labels `alpha`, the log-return gap. | The page now tells the user one story in the high-level surfaces, then a different numeric basis in the proof chart. For PRU/GDX, the same large-spread episode can appear around +66% in dots but around +94% in the strip. Beat sign is invariant, so the headline count is not broken, but the displayed magnitude is inconsistent. This violates the "one normalize boundary / label every number with its basis" rule. | Convert `_build_dots_svg` to use `alpha_simple` for y-scale, tooltip, and axis label. Keep persisted `beat` for color. Rename the axis to simple outperformance vs benchmark. Add a test with log != simple asserting strip and dots show the same episode magnitude. |
| MEDIUM | B | `golden_vector/lab/conditional_dial.py:925`, `golden_vector/lab/conditional_dial.py:927`, `golden_vector/lab/conditional_dial.py:928`, `golden_vector/lab/conditional_dial.py:1048`, `golden_vector/lab/conditional_dial.py:1098`, `golden_vector/lab/conditional_dial.py:1143`, `golden_vector/serve/lab_curve_data.py:148`, `golden_vector/serve/lab_curve_data.py:292`, `golden_vector/serve/lab_curve_data.py:302`, `golden_vector/serve/lab_curve_data.py:480` | The lab build records run-stamped artifacts in `dial_meta.json`, but readers still open mutable `*_latest.parquet` aliases directly. The writer updates latest aliases before the meta file is atomically replaced. | This leaves a crash window where one or more latest aliases can be new while `dial_meta.json` is old. If schema/config hash did not change, `_artifact_is_current` can still pass while the four frames are not from one coherent build. The dashboard then violates the repo's data-spine rule: one atomic pointer should define the current artifact set. | Make `dial_meta.json` the current-state pointer: write run-stamped artifacts first, write latest aliases as convenience outputs only, then atomically publish meta with artifact names. Serve loaders should resolve `run_stamped_artifacts` from the meta, not hard-coded latest filenames. Add a fault-style test where latest aliases are mixed and meta still points to the previous coherent set. |
| LOW | A | `golden_vector/serve/lab_curve_page.py:483`, `golden_vector/serve/lab_curve_page.py:488`, `golden_vector/serve/lab_curve_page.py:489`, `golden_vector/serve/lab_curve_page.py:507`, `tests/test_lab_curve.py:953` | The distribution-strip median marker clamps to the plot edge when the persisted median falls outside the displayed tick range, but text and aria still say `median X%` without saying it was pinned/off-scale. | In the real schema-3 artifact I checked, the marker sits among the ticks. So this is not currently misleading for PRU/KGC. But the defensive path is explicitly tested and can render a marker at the edge while announcing a median far outside the axis range. That makes the visual position dishonest in the rare case the guard is needed. | Either expand the axis to include the persisted median or label the marker/title/aria as `median X% (off scale, pinned at edge)`. Add the wording to `test_distribution_strip_clamps_out_of_range_median`. |
| LOW | B | `tests/test_lab_curve.py:532`, `tests/test_lab_curve.py:923`, `tests/test_lab_curve.py:1015`, `tests/test_lab_page.py:176` | The tests cover surfaces individually, but there is no full-page integration test proving that profile label, headline, win-rate bar, distribution strip, dots, and benchmark toggle agree on one rendered page. | This exact feature has had stage-by-stage fixes where each unit looked correct, but the cross-surface page still had basis drift. The biggest remaining risk is integration drift, not isolated math. | Add one end-to-end rendered-page test using a fixture where raw != shrunk and log != simple. Assert the selected ticker/benchmark/horizon renders one basis, matching headline/bar/strip/dots wording, and that a thin ticker suppresses label/headline/strip while keeping context honest. |
| NIT | B | `golden_vector/serve/overview_lab.py:1`, `golden_vector/serve/overview_lab.py:4`, `golden_vector/serve/overview_lab.py:86`, `golden_vector/serve/overview_lab.py:90`, `golden_vector/serve/lab_curve_page.py:361`, `golden_vector/serve/lab_curve_page.py:369`, `golden_vector/serve/lab_curve_data.py:391`, `golden_vector/serve/lab_curve_data.py:420` | Some "render-only" / "never counts" claims overstate the implementation. Serve code does small display counts for rows, scenario points, above-zero count, and usable down/up buckets. | I am not treating this as a model-boundary violation: the counts are display summaries over already persisted rows, not ranking or model math. But the wording matters because this project uses "backend computes, serve renders" as an architecture guardrail. Overstating the boundary makes future reviews harder. | Reword comments/records to "no model aggregation, ranking, shrinking, or ratio math in serve; display-only counts over already loaded rows are allowed." If the rule is interpreted strictly, persist these counts too. |
| NIT | B | `golden_vector/serve/lab_curve_data.py:391`, `golden_vector/serve/lab_curve_data.py:417`, `golden_vector/serve/lab_curve_data.py:419`, `tests/test_lab_curve.py:741` | `_ticker_profile` still derives usable down/up counts in the loader. It uses the shared `cell_bucket_is_usable` rule and has a drift test, so it is not a duplicate-rule bug. | This is acceptable today, but it is close to the boundary. If product copy starts relying on those counts more heavily, this should be persisted rather than derived in serve-land. | Leave as-is for now or move `usable_down_bucket_count` / `usable_up_bucket_count` fully into the rendered payload. The current drift test is the minimum acceptable guard. |

## Part A Detailed Notes

The v3 basis fix is substantively correct.

- `DIAL_SCHEMA_VERSION = 3` is present at `golden_vector/lab/conditional_dial.py:86`.
- `alpha_simple` is part of the episode schema at `golden_vector/lab/conditional_dial.py:384`.
- `build_episode_artifact` computes `alpha_simple = exp(alpha) - 1` at `golden_vector/lab/conditional_dial.py:468`.
- The detail reader carries both `alpha` and `alpha_simple` at `golden_vector/serve/lab_curve_data.py:319` and `golden_vector/serve/lab_curve_data.py:320`.
- The distribution strip plots `alpha_simple` and uses the persisted benchmark-specific `median_alpha_*` at `golden_vector/serve/lab_curve_page.py:415` through `golden_vector/serve/lab_curve_page.py:428`.
- The GDX-only legacy `build_episode_frame` path still returns the old narrow columns, so the parity gate is not forced to know about `alpha_simple`.

The prior claim that the strip is now one-basis is true for the strip itself. The claim becomes overstated only if read as "the whole drill-down is one basis," because the dots chart remains log alpha.

## Part B Detailed Notes

The page mostly tells a coherent story for PRU and KGC:

- PRU/GDX renders Defensive, about 74% down-side profile rate, 31% up-side profile rate, headline 90.5%, win-rate 91%, median +25%, and a distribution from about -47% to +94%.
- PRU/GDXJ renders Defensive, headline 92.9%, win-rate 93%, median +29%, and a distribution from about -10% to +103%.
- KGC/GDX renders Pro-cyclical, headline 39.2%, win-rate 39%, median about -2%.
- A thin ticker such as AAUC.TO degrades rather than showing a confident profile/headline/strip.

The main holistic problem is not the labels or counts; it is basis consistency. A non-expert will read the collapsed "When did it happen?" chart as proof for the distribution strip. If those two charts express the same weeks in different return bases, the user has to understand log returns to reconcile the page. That is not the right default for this product.

## Overstatement / Commit-Record Checks

- "v3 basis fixed" is accurate for the distribution strip, not for the whole drill-down.
- "render-only" / "never counts" is overstated. Serve does display-only counts. I do not consider those counts harmful, but the claim should be tightened.
- "cannot drift end-to-end" is overstated until there is a full-page agreement test and the dots chart is moved to the same return basis.
- "current lab artifacts are coherent" is not guaranteed by the reader path because serve reads mutable latest aliases instead of the run-stamped files named by `dial_meta.json`.

## Recommendation

I would fix the two MEDIUM items before treating the gold-profile dashboard as done:

1. Make the dots chart use `alpha_simple` so the whole page speaks in simple-return percentages.
2. Make `dial_meta.json` the atomic artifact pointer for all lab readers.

The clamp wording and test coverage items are smaller but worth doing in the same cleanup because they directly target the kind of cross-surface drift this review found.
