# Review: Lab Relative Performance Curve Plan v2

Verdict: NEEDS CHANGES

I reviewed `reviews/codex/claude_lab_relative_performance_curve_plan_v2.md` first-hand against the current code and cached data. I assumed this was the intended `plan_v2.md`; there is no file literally named `plan_v2.md`.

The product idea is strong: let Emanuel click a Conditional-Dial probability and see the actual historical dots behind it. The core engineering direction is also right: reuse `build_forward_return_panel`, keep serve read-only, carry effective-N/Wilson caveats, and treat GDXJ as a separate benchmark with its own missing-history behavior.

But the plan is not build-ready because the locked top decisions and the lower implementation sections contradict each other in several places. If two engineers implemented this as written, one would build a 13w-only two-variant feature and the other would build a 13/26/52w six-variant feature.

## Checked

- `golden_vector/lab/conditional_dial.py`
- `golden_vector/lab/forward_returns.py`
- `golden_vector/features/weekly_returns.py`
- `golden_vector/lab/ledger.py`
- `golden_vector/serve/lab_data.py`
- `golden_vector/serve/overview_lab.py`
- `golden_vector/serve/charts.py`
- existing Lab tests
- local cached weekly data, no live fetch

The plan's measured horizon evidence is correct on my local run:

| Horizon | Usable cells | Gold-down usable |
|---:|---:|---:|
| 13w | 180 / 325 | 54 / 65 |
| 26w | 148 / 323 | 0 / 64 |
| 52w | 0 / 312 | 0 / 64 |

That means Emanuel's decision to expose 26w/52w is allowed as a product choice, but the empty-state/evidence handling must be explicit and tested.

## High Findings

### H1. The plan still has a 13w-only implementation body after locking 13/26/52w

The locked decisions say to wire `13w + 26w + 52w` and register `2 benchmarks x 3 horizons = 6` variants (`reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:12`, `:27-37`). But the build section still repeatedly specifies 13w-only artifacts and metadata:

- `dial_episodes_13w_latest.parquet` at `reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:173` and `:215`.
- `build_forward_return_panel(weekly, horizons_weeks=[13])` at `:180` and `:209`.
- v1 columns only include `alpha_gdx`, `beat_gdx`, no `horizon_weeks` or `benchmark` at `:215-218`.
- v2 says `n_trials = 2` at `:280`, and tests say "Ledger has exactly two dial variants" at `:305`.
- Honesty labels still say every number has horizon `13w forward` at `:331`.

Current code is also 13w-fixed: `golden_vector/lab/conditional_dial.py:207` defines `DIAL_TABLE_FILENAME = "dial_table_13w_latest.parquet"`, `golden_vector/lab/conditional_dial.py:208` defines the 13w meta filename, and `golden_vector/serve/lab_data.py:40` reads that fixed filename.

Fix: choose one implementation contract and make every section match it. If locked decisions stand, the artifact should be generic, probably `dial_episodes_latest.parquet` plus `dial_table_latest.parquet`, long-form by `ticker, horizon_weeks, benchmark, week_period/bucket`, and all loaders/routes/tests must accept `horizon_weeks` and `benchmark`. The lower plan must stop saying `13w_latest`, `horizons_weeks=[13]`, and `n_trials=2`.

### H2. Six-variant pre-registration is not wired through the actual ledger contract

The top says "Register ALL SIX in the ledger BEFORE compute; persist all six hashes in meta; disclose `n_trials = 6`" (`reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:27-30`). Later the plan says to loop only GDX/GDXJ and persist `n_trials = 2` (`:192-196`, `:280`, `:305`, `:342-343`).

The current ledger contract is exact-config based: `golden_vector/lab/ledger.py:46-88` registers one config hash at a time, and `golden_vector/lab/ledger.py:130-136` computes `n_trials` by counting ledger records. That means the build must register each `(benchmark, horizon)` config separately and then read the trial count back from the ledger, not hand-stamp a hardcoded `6`.

Fix: specify one `signal_id`, likely `conditional_dial_analog`, and six configs `{benchmark, horizon_weeks, bucket_defs, min_effective_n, eb_prior_strength}`. The meta should include `variant_hashes_by_benchmark_horizon` and `n_trials = n_trials(lab, signal_id="conditional_dial_analog")` or a family-filtered equivalent. Add a test that changing either benchmark or horizon changes the hash and that all six are registered before compute proceeds.

### H3. The table shape is underspecified for "rank by GDX, GDXJ as comparison" across three horizons

The locked decision says rank by GDX and show GDXJ as a comparison column (`reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:25`). The v2 section says to add a GDXJ column next to GDX and keep one backend rank (`:282-286`). That is clear for one horizon, but not for three.

For 13/26/52w, the table needs an explicit key and ranking contract:

- Is there one row per `(ticker, bucket, horizon_weeks)` with GDX and GDXJ columns?
- Or one row per `(ticker, bucket, horizon_weeks, benchmark)`?
- If long-form includes `benchmark`, where does the GDX-ranked row live?
- At 26w/52w, does a fully insufficient GDX cell get no rank even if GDXJ happens to have data?

Current `build_dial_table` produces one row per `(ticker, bucket)` and ranks by `p_beat_gdx_shrunk` in `golden_vector/lab/conditional_dial.py:148-157`. Existing serve sorts only by `rank_in_bucket` in `golden_vector/serve/lab_data.py:62`, and renders hard-coded GDX columns at `golden_vector/serve/overview_lab.py:89-93` and `:125-126`.

Fix: define two artifacts:

- `dial_cells_latest.parquet`: one row per `(ticker, bucket, horizon_weeks)` with GDX-ranked fields plus GDXJ comparison fields.
- `dial_episodes_latest.parquet`: one row per `(ticker, bucket, horizon_weeks, benchmark, week_period)`.

Alternatively make both artifacts long-form by benchmark, but then add a derived GDX-ranked table for the overview. Do not leave this implicit.

### H4. The plan says serve does no arithmetic, but Chart A as written would need derived non-overlap marker logic in render

The architecture says all per-week gold bucket, alpha/beat flags, relative-strength series, effective N, and Wilson bands are computed in the Lab build, with serve only filtering/formatting (`reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:168-171`). Good.

But Chart A asks for "independent (non-overlapping) episodes drawn as larger markers" (`:235-236`) without listing a persisted column for it. The v1 artifact columns at `:215-218` do not include an `is_independent_episode`, `episode_stride_index`, or similar field. If serve derives this from row positions or dates, it becomes logic in the UI.

Fix: persist the marker classification in the episode artifact, e.g. `is_nonoverlap_anchor`, computed per `(ticker, horizon_weeks, benchmark)` in the build. The render should only choose marker size from that boolean.

## Medium Findings

### M1. `build_forward_return_panel` reuse is correct, but the plan still keeps a second gold-forward path

The plan correctly says to consume `build_forward_return_panel` because it already emits `fwd_alpha_gdx_{h}w` and `fwd_alpha_gdxj_{h}w` for any horizon (`golden_vector/lab/forward_returns.py:20-48`). It also correctly identifies the current private fork in `golden_vector/lab/conditional_dial.py:161-181`.

But Step 1.1 says to "left-merge the panel's `fwd_alpha_gdx_13w` onto the dial's own `gold_fwd_simple`/`gold_bucket` join" (`reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:208-214`). That keeps half the private episode math alive.

Fix: centralize the whole episode-label panel, not only alpha. Either extend `build_forward_return_panel` to emit `fwd_gold_log_ret_{h}w` or add a new `build_conditioning_episode_panel` that consumes the forward panel and computes `gold_fwd_simple` once. Then both dial cells and chart rows consume that same episode panel.

### M2. The locked horizon decision makes the "single 13w view" explanation stale

Section 3 still says "Recommendation: ship 13w ONLY" (`reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:120`) and explains "How relevance-vs-evidence is made visible (on the single 13w view)" (`:135`). The top says the opposite: expose 13/26/52w while showing evidence collapse (`:12-20`).

Fix: rewrite Section 3 as "Why longer horizons are visible but often empty." Keep the measured table, but remove "ship 13w only" language. This matters because Emanuel will read the plan, and the current version looks like it disagrees with his own locked decision.

### M3. Current route shape conflicts with the locked 3-horizon design

The plan says v1 renders inline on `/lab`, then v2 promotes to `/lab/dial/<ticker>?scenario=<bucket>&benchmark=<GDX|GDXJ>` (`reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:228-230`, `:292-295`). With the locked decision, horizon is also required. It cannot be hidden in the artifact name.

Fix: make the route explicit from the start:

`/lab/dial/<ticker>?scenario=<bucket>&benchmark=GDX&horizon=13`

The overview `/lab` should also accept `bucket` and `horizon`, defaulting to 13w. If 26w/52w are selected, the one-line empty-state banner should be tied to that route/query value.

### M4. Artifact persistence outside the model-state manifest is acceptable for Lab, but the plan should still avoid stale lab artifacts

The plan is right that current Lab precedent is direct-path read outside the model-state manifest: `golden_vector/serve/lab_data.py:40` reads `lab_dir(paths) / DIAL_TABLE_FILENAME`. That is acceptable because this is exploratory Lab, not production model state.

However, once the plan adds 6 variants and multiple route parameters, stale artifacts become easier to misread. The current `DIAL_META_FILENAME` is fixed at `golden_vector/lab/conditional_dial.py:208`, and current meta only stores one `horizon_weeks` and one hash at `golden_vector/lab/conditional_dial.py:263-269`.

Fix: keep direct-path persistence, but add a lab artifact schema/version and config fingerprint in the meta. The loader should fail closed if the artifact lacks required columns for the selected horizon/benchmark.

### M5. GDXJ per-week degradation is the right call, but the artifact should carry benchmark-specific counts beside the cell

The plan correctly says GDXJ must degrade per-week, not per-ticker (`reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:274-280`). Current weekly returns already support missing GDXJ independently: `golden_vector/features/weekly_returns.py:19-22` maps both benchmarks, and `golden_vector/features/weekly_returns.py:82-110` joins benchmark returns outer-by-week.

Fix: require both `n_weeks_gdx/effective_n_gdx` and `n_weeks_gdxj/effective_n_gdxj` on the overview row if GDXJ is a comparison column. Do not make the UI infer the GDXJ evidence from the GDX row.

### M6. The chart builder seam is reasonable, but "serve guardrail forbids `* 100`" is too blunt

The plan wants a serve guardrail forbidding tokens including `* 100` in `lab_curve_data.py` / `lab_curve_page.py` (`reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:266-268`). That can create false positives because formatting percentages may legitimately multiply a persisted fraction by 100 in a formatter, or call an existing helper that does.

Fix: forbid alpha/beat/rebase primitives (`forward_sum`, `.rolling`, `.cumsum`, `np.exp`, `build_forward_return_panel`) in serve, but allow standard formatting helpers. If the policy is "no multiplication at all," then store display-ready percentage values in the DTO and say that explicitly.

## Nits / Clarity

- The plan says "Artifact size -> ~65 tickers x ~158 weeks x (1-2 benchmarks) ~ <25k rows" (`reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:345`), but with 3 horizons and 2 benchmarks the upper bound is closer to 65 x 158 x 3 x 2 before NA drops, around 61k rows. Still small, but update the estimate.
- The phrase "with ~3 years of weekly history" (`reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:123`) is confusing because the system has longer price history; the effective independent episode count is the issue. Say "within the available scenario buckets, after effective-N adjustment" instead.
- The plan should say whether the `week_date` column is a timestamp/date or derived from `week_period`. Current code stores `week_period` as a W-FRI string in `golden_vector/features/weekly_returns.py:123-124`.
- The plan should explicitly state that `alpha == 0` is a miss for both GDX and GDXJ. It says this in tests for v1 only (`reviews/codex/claude_lab_relative_performance_curve_plan_v2.md:253-256`), but it should apply to every benchmark/horizon.

## What I Would Build After Fixes

1. Build one backend episode panel from weekly returns and `build_forward_return_panel(weekly, horizons_weeks=[13, 26, 52])`.
2. Persist `dial_episodes_latest.parquet` long-form by `ticker, week_period, horizon_weeks, benchmark`.
3. Persist `dial_cells_latest.parquet` as the overview table by `ticker, bucket, horizon_weeks`, ranked by GDX and carrying GDXJ comparison/evidence columns.
4. Register six variants before compute, then write all six hashes and the ledger-derived trial count into meta.
5. Add `/lab?horizon=13&bucket=...` and `/lab/dial/<ticker>?horizon=13&scenario=...&benchmark=...`.
6. Keep 26w/52w visible but make their empty/insufficient state impossible to miss.
7. Move every chart-derived flag into the artifact; serve only filters and renders.

## Final Recommendation

Do not code from the current plan as written. The core idea is good and most technical instincts are correct, but the plan needs one cleanup pass to reconcile the top locked decisions with the lower implementation steps.

Once the plan consistently says "3 horizons, 2 benchmarks, 6 variants, generic artifacts, explicit horizon route," I would grade it READY WITH MINOR CHANGES.
