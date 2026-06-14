# Codex Review - Lab Curve + Scorecard After Claude Changes

Verdict: READY WITH CHANGES

I reviewed the current `dev-vic` implementation after Claude's latest Lab and
Scorecard changes. This was read-only: I did not change product code. I checked
the current code, persisted local Lab/Scorecard artifacts, route defaults, and a
focused test slice.

## Checks Run

- `python -m pytest tests/test_lab_curve.py tests/test_lab_page.py tests/test_lab_scorecard.py -q`
  - Result: `29 passed in 67.35s`
- Local artifact inspection:
  - `data/lab/dial_cells_latest.parquet`: 1,260 rows, horizons `[4, 8, 13, 26]`
  - `data/lab/dial_episodes_latest.parquet`: 434,442 rows, benchmarks `GDX/GDXJ`
  - `data/lab/dial_relstrength_latest.parquet`: 110,218 rows
  - `data/lab/scorecard_latest.parquet`: 9 rows

## Overall Assessment

The Lab curve implementation is materially better than the older plan. Moving
from the weak 13/26/52 design to 4/8/13/26 is a good product call: 4w and 8w
add useful countable evidence, 13w remains the default, 26w is still useful for
flat/up scenarios, and the fully empty 52w lens is gone. The architecture is
mostly right: backend computes the episode/cell artifacts, the serve layer
filters and renders, and the focused tests are green.

The main remaining issues are user-facing honesty and a few freshness/schema
guards. The Scorecard especially needs clearer language. It currently says a
SUPPORTED verdict means the ranking "genuinely predicted what it claims"; that
is too strong for survivor-only exploratory backtests, especially where the
median outcome ceiling is low. The page should say the ranking "passed this
pre-registered historical test" and make the low/noisy effect size visible.

## Findings

### HIGH 1 - Scorecard copy overstates what the evidence proves

Evidence:
- `golden_vector/serve/overview_scorecard.py:41-45` says a SUPPORTED verdict
  means the ranking "genuinely predicted what it claims."
- `data/lab/scorecard_latest.parquet` has supported backtests with low median
  ceilings: E2 `0.149`, E3 `0.078`, E3b `0.091`.
- The meta caveats correctly say survivor-only and "SUPPORTED, not VALIDATED",
  but the headline copy is stronger than the caveat.

Why it matters:
Emanuel is using this as a trust screen. The tool should not imply model proof
when the evidence is "this passed our locked historical test under known
caveats." Low ceiling means the per-name outcome is noisy even when the
cross-sectional ordering survives.

Concrete fix:
Replace the headline with plain language such as: "SUPPORTED means this ranking
passed a pre-registered historical test in the surviving-name universe. It is
evidence, not proof." Add a small "effect/noise" label on each supported card,
for example "Effect looks small/noisy" when `median_ceiling` is below a pinned
threshold. Do not change gates silently; this is display honesty.

### HIGH 2 - Scorecard renders literal `nan` in the first backtest card

Evidence:
- `golden_vector/serve/overview_scorecard.py:30-36` only treats `None` as blank.
  It formats pandas/NumPy NaN as the string `nan`.
- The current scorecard artifact has NaN values for E1a `nw_t`,
  `tercile_spread_mean`, `tercile_spread_t`, and `median_ceiling`.
- Rendering `_render_scorecard_page(load_scorecard_data(paths))` currently
  contains snippets like `t nan`, `spread nan (t nan)`, and
  `outcome split-half consistency nan`.

Why it matters:
This is a visible credibility bug on the page whose job is to tell the user
whether the evidence is credible.

Concrete fix:
Make `_fmt` treat non-finite floats as `-`. Also avoid rendering stats that do
not apply to a given experiment, rather than showing placeholders inside a
sentence. Add a regression test using an E1a-like row with NaNs.

### MEDIUM 1 - `/lab` defaults to an extreme gold-down bucket, not the normal downside lens

Evidence:
- `golden_vector/serve/workspace.py:355-367` passes `bucket=None` when no query
  parameter is supplied and then selects `lab_data.buckets[0][0]`.
- `golden_vector/serve/lab_curve_data.py:174-186` sorts buckets by
  `BUCKET_LABELS` order.
- `golden_vector/lab/conditional_dial.py:35-47` orders `gold_down_big` before
  `gold_down`.
- Current `/lab` data therefore defaults to `gold_down_big` ("Gold down more
  than 15%"), not the more useful `gold_down` ("Gold down 5% to 15%").

Why it matters:
The default screen should show the most useful, explainable evidence. The
extreme-down bucket often has zero usable cells at 4/8/13 weeks and can make the
Lab look empty or broken.

Concrete fix:
Default `/lab` to `horizon=13` and `bucket=gold_down` if available. Keep
`gold_down_big` selectable, but treat it as an extreme stress lens. Add a route
test asserting the initial page selects `gold_down`.

### MEDIUM 2 - Relative-strength Chart B does not validate freshness/config like the other Lab artifacts

Evidence:
- `golden_vector/serve/lab_curve_data.py:154-161` validates cells against
  `_artifact_is_current(meta)`.
- `golden_vector/serve/lab_curve_data.py:213-220` validates the episodes path
  against the same meta before rendering the curve.
- `golden_vector/serve/lab_curve_data.py:271-296` loads
  `dial_relstrength_latest.parquet` and only checks required columns; it does
  not check the same schema/config freshness before rendering Chart B.

Why it matters:
Chart B is explicitly secondary, but it is still user-visible evidence. If the
relstrength artifact is stale while cells/episodes are current, the page can
mix coherent evidence with stale context.

Concrete fix:
Make `_relstrength_points` share the same `_artifact_is_current(meta)` gate, or
store/check a separate relstrength schema/config fingerprint. A stale Chart B
should show the existing calm "rebuild Lab artifacts" message, not render stale
points.

### MEDIUM 3 - Scorecard reader lacks a schema/required-column guard

Evidence:
- `golden_vector/serve/scorecard_data.py:31-57` reads
  `scorecard_latest.parquet`, splits records by `kind`, and returns them as
  available.
- It does not check a schema version, required columns, artifact/meta match, or
  whether the artifact is stale relative to the current Scorecard code.
- The Lab curve reader already has stronger shape/config guards in
  `golden_vector/serve/lab_curve_data.py:122-138`.

Why it matters:
The Scorecard is the trust layer. A stale or partial parquet should produce a
friendly "rebuild scorecard" state, not a page of blanks or misleading cards.

Concrete fix:
Add a scorecard schema version and required-column set. The loader should return
`STALE` or `CORRUPT` when old artifacts are missing fields such as
`signal_id`, `kind`, `verdict`, `claim`, `mean_ic`, `median_ceiling`,
`variant_hash`, and `baseline_lines`. Keep the page calm, but fail loud.

### MEDIUM 4 - Dial meta reports `n_trials=10` while the active variant set has 8 hashes

Evidence:
- `golden_vector/lab/conditional_dial.py:635-650` registers every active
  `(benchmark, horizon)` variant.
- Current active horizons/benchmarks are 4 horizons x 2 benchmarks = 8 hashes.
- `golden_vector/lab/conditional_dial.py:710` writes `n_trials` from the whole
  ledger family. Current `data/lab/dial_meta.json` has `n_trials=10` and 8
  active hashes.

Why it matters:
Statistically, counting retired exploratory variants may be conservative, but
the page/meta should make the distinction clear. Otherwise the user sees a
trial count that does not match the visible lenses.

Concrete fix:
Keep the conservative ledger count if that is the intended multiple-testing
discipline, but add explicit fields:
- `active_variant_count: 8`
- `registered_family_trials: 10`
- `retired_variant_count: 2`

Then render/explain them as "8 visible lenses, 10 total registered Lab trials."

### MEDIUM 5 - The Lab charts use equal index spacing, not actual date spacing

Evidence:
- `golden_vector/serve/lab_curve_page.py:190-277` positions Chart A dots by
  row index.
- `golden_vector/serve/lab_curve_page.py:307-358` positions Chart B line points
  by row index.

Why it matters:
The x-axis labels are dates, so the visual reads as time. Equal spacing is fine
if every week is present, but missing periods/gaps can make time intervals look
more regular than they are.

Concrete fix:
Map `week_date` to an actual date-scale x coordinate. If the date parse fails,
fall back to index spacing and show a calm chart-status message.

### LOW 1 - The implementation plan/doc text is stale after Claude's horizon change

Evidence:
- `reviews/codex/claude_lab_relative_performance_curve_plan_v3.md` still
  describes locked horizons `13w + 26w + 52w` and six variants.
- Current implementation uses `DIAL_HORIZONS_WEEKS = [4, 8, 13, 26]` at
  `golden_vector/lab/conditional_dial.py:52-56`.

Why it matters:
The code change is a good one, but future reviewers will be confused if the
current plan still describes a different artifact and trial family.

Concrete fix:
Add a short v4 handoff or patch the plan changelog to say: 52w was dropped,
4w/8w were added, active visible variants are 8, and `n_trials` may include
retired registered variants.

### LOW 2 - Conditional Dial module docstring still says 13-week / GDX only

Evidence:
- `golden_vector/lab/conditional_dial.py:1-6` still describes only "next 13
  weeks" and "P(beat GDX)".
- The implementation is now multi-horizon and multi-benchmark.

Concrete fix:
Update the docstring so future maintainers do not assume the old single-lens
contract.

### LOW 3 - Scorecard accrual silently ignores corrupt vintage stores

Evidence:
- `golden_vector/lab/scorecard.py:125-129` catches any parquet read exception
  in `_accrual_rows` and continues.

Why it matters:
Forward accrual is optional, so this is not a blocker. But a corrupt vintage
store should at least appear in scorecard meta or a warning; otherwise the
accrual count can be quietly understated.

Concrete fix:
Collect skipped/corrupt vintage filenames in meta and render a small warning on
the Scorecard page. Do not fail the whole scorecard unless a required backtest
input is corrupt.

## Scorecard Product Assessment

The current Scorecard is directionally valuable, but I would change how it is
presented before asking Emanuel to trust it:

1. Rename the page concept from "Does each tool work?" to something closer to
   "Evidence scorecard". This is less binary and more honest.
2. Replace "genuinely predicted" with "passed this locked historical test."
3. Add a one-line explanation for each card:
   - "IC: did higher-ranked names later do better?"
   - "Spread: did the top group beat the bottom group?"
   - "Ceiling: how noisy was the outcome itself?"
4. Add a simple "effect size" badge. A supported but low-ceiling signal should
   not feel as strong as a supported signal with a stable/high ceiling.
5. Keep the survivor-only caveat visible at the top, not only in a help tooltip.

This keeps the Scorecard useful without inventing another composite rank.

## Lab Ideas Worth Considering

These are product ideas, not required fixes.

1. Conservative sort: let the user sort by the lower Wilson bound, not only the
   point estimate. That answers "which names looked better even after uncertainty?"
2. Similar episodes: for a selected ticker/scenario, show the 5 historical
   episodes most similar to the current gold move and the subsequent stock-vs-GDX
   result.
3. Portfolio Lab lens: apply the same scenario table to current holdings, so the
   user sees which owned names historically beat/lagged GDX in the selected gold
   scenario.
4. Compare two tickers: overlay two selected miners in the same scenario so the
   user can see whether one was consistently better or just had a few outliers.
5. Regime filters, but clearly exploratory: high/low volatility, rising/falling
   gold trend, or high/low dollar regimes. These should be marked exploratory and
   not used for Scorecard claims until pre-registered.
6. Data coverage map: a small panel showing how many countable episodes exist by
   horizon and bucket. This would explain instantly why some rows are grey.
7. Survivor-bias roadmap: show the limitation plainly and track future work to
   include delisted/failed miners. This is the biggest honesty gap in the Lab.

## Recommended Fix Order

1. Fix Scorecard `nan` formatting and soften the overclaiming copy.
2. Change `/lab` default bucket to `gold_down`.
3. Add Scorecard schema/required-column guard.
4. Add relstrength freshness/config guard.
5. Clarify active vs ledger trial count in Lab meta/UI.
6. Patch the stale plan/docstring.
7. Date-scale the Lab charts when time allows.

The current implementation is usable for review, but I would not treat the
Scorecard page as user-ready until the first two fixes land.
