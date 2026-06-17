# Codex Review: `claude_capture_behavior_engine_plan.md`

Reviewed on 2026-06-17 from `dev-vic`.

Scope: plan review only. I read the plan and spot-checked the current Lab/serve code it depends on:
`golden_vector/lab/conditional_dial.py`, `golden_vector/lab/forward_returns.py`,
`golden_vector/serve/lab_curve_data.py`, `tests/test_lab_page.py`, and the global serve guard.

No product code was edited. Tests were not run because this is a plan review.

## Findings

### HIGH - Peer percentile is grouped by benchmark even though the ranked return is benchmark-independent

Where:
- `reviews/codex/claude_capture_behavior_engine_plan.md:97`
- `reviews/codex/claude_capture_behavior_engine_plan.md:256`
- `golden_vector/lab/conditional_dial.py:445`
- `golden_vector/lab/conditional_dial.py:476`

The plan computes `peer_count` / `peer_percentile` within
`(week_period, horizon_weeks, benchmark, gold_bucket)`, but the value being ranked is
`stock_fwd_simple`. That return does not depend on GDX or GDXJ. The current episode builder expands
each ticker/week/horizon once per benchmark, so this plan would create two benchmark-scoped peer
percentiles for the same stock return and gold scenario.

That is easy to misread later: the UI could show a different "peer rank" for GDX vs GDXJ even though
the peer question is independent of those benchmarks, or downstream aggregation can double-count the
same stock-return event.

Concrete fix:
- Compute peer ranks on distinct `(ticker, week_period, horizon_weeks, gold_bucket)` stock-return
  rows before benchmark expansion, or group by `(week_period, horizon_weeks, gold_bucket)` only.
- Join the same `peer_count` / `peer_percentile` onto both benchmark rows.
- If a benchmark-specific eligible universe is ever desired, make that a separate metric with a
  separate name and contract.
- Add a test where one stock/week/horizon appears under both GDX and GDXJ and asserts the peer
  percentile is identical and not double-counted.

### MEDIUM - The plan folds behavior thresholds into `dial_config_hash`, which over-invalidates the raw episode spine

Where:
- `reviews/codex/claude_capture_behavior_engine_plan.md:321`
- `reviews/codex/claude_capture_behavior_engine_plan.md:348`
- `golden_vector/lab/conditional_dial.py:117`
- `golden_vector/lab/conditional_dial.py:135`
- `golden_vector/lab/conditional_dial.py:1087`
- `golden_vector/serve/lab_curve_data.py:188`

The current Lab has one `dial_config_hash` for the dial artifact family. The plan adds
`CaptureBehaviorConfig` to that same hash, including thresholds like `q_fdr`,
`hedge_down_capture_max`, `torque_up_capture_min`, and `alpha_slope_threshold`.

Those thresholds affect the new capture/trend interpretation artifacts, not the raw episode spine.
If they are folded into the one existing hash, a label-threshold edit can make `dial_episodes`,
`cells`, `profile`, and the existing Lab page appear stale until the whole dial family is rebuilt.
That is technically safe, but it makes unrelated raw data look invalid and increases the chance of
operator confusion.

Concrete fix:
- Keep a raw `dial_config_hash` for the episode/cell/profile spine.
- Add a separate `behavior_config_hash` for `dial_capture` and `dial_behavior_trend`.
- Stamp both hashes in metadata when needed, and make serve validate the hash relevant to the artifact
  it is reading.

### MEDIUM - `min_peer_count` should not null the raw episode percentile

Where:
- `reviews/codex/claude_capture_behavior_engine_plan.md:97`
- `reviews/codex/claude_capture_behavior_engine_plan.md:265`
- `reviews/codex/claude_capture_behavior_engine_plan.md:336`
- `reviews/codex/claude_capture_behavior_engine_plan.md:350`

The plan says `peer_count < min_peer_count` makes the episode-level percentile null. That mixes a
presentation/config threshold into the base episode artifact. A future `min_peer_count` change would
change old episode rows even though the underlying peer rank did not change.

Concrete fix:
- Persist raw `peer_count` and raw `peer_percentile` when `peer_count >= 2`.
- Persist `peer_percentile = null` only for mathematically undefined cases, such as `peer_count < 2`.
- Apply `THIN_PEER_POOL` and any null-for-display behavior in `dial_behavior_trend` or a render-ready
  artifact using `min_peer_count`.
- Add tests for `peer_count` 1, ties, and a threshold change that should not mutate episode rows.

### MEDIUM - Capture headline sample basis is not pinned tightly enough

Where:
- `reviews/codex/claude_capture_behavior_engine_plan.md:183`
- `reviews/codex/claude_capture_behavior_engine_plan.md:198`
- `reviews/codex/claude_capture_behavior_engine_plan.md:245`
- `golden_vector/lab/conditional_dial.py:476`
- `golden_vector/lab/conditional_dial.py:483`

The plan is strict that significance tests use `is_nonoverlap_anchor`, but the capture ratio formula
is described as operating over a ticker's down/up "episodes". Effective N floors reduce overconfidence,
but they do not stop overlapping weekly labels from dominating the actual mean return ratio.

This matters because the capture headline is a magnitude metric. If the numerator and denominator are
computed over overlapping rows, a persistent multi-week move can be counted many times in the mean,
even if the effective N says the evidence is thin.

Concrete fix:
- Define the headline capture sample explicitly.
- Prefer computing headline and gating capture on `is_nonoverlap_anchor` rows.
- If all-row capture is retained for smoothness, persist both `capture_all_rows` and
  `capture_anchor`, make the anchor version the trust/gating number, and test that overlapping rows
  cannot manufacture a stronger archetype than anchors support.

### MEDIUM - Event-time recent/older split needs an exact grouping grain

Where:
- `reviews/codex/claude_capture_behavior_engine_plan.md:220`
- `reviews/codex/claude_capture_behavior_engine_plan.md:229`
- `reviews/codex/claude_capture_behavior_engine_plan.md:236`
- `reviews/codex/claude_capture_behavior_engine_plan.md:251`
- `reviews/codex/claude_capture_behavior_engine_plan.md:327`

"Most recent half of independent anchors" is the right direction, but the plan does not fully pin
whether the split is made before or after filtering to a bucket/direction. If the split is made across
all anchors first and then filtered to gold-down/gold-up, one side can still end up thin or compare a
different regime mix than intended.

Concrete fix:
- For bucket trend, split within `(ticker, benchmark, horizon, bucket)` after filtering to anchor rows.
- For capture trend, split within `(ticker, horizon, direction)` after filtering to `DOWN_BUCKETS` or
  `UP_BUCKETS` anchor rows.
- Persist recent/older anchor counts and the split index/cutoff used for each cell.
- Add tests with uneven up/down event spacing to prove the split is event-time within the target
  bucket/direction.

### LOW - `bench_fwd_simple` recovery wording invites a log/simple mix-up

Where:
- `reviews/codex/claude_capture_behavior_engine_plan.md:88`
- `reviews/codex/claude_capture_behavior_engine_plan.md:93`
- `golden_vector/lab/forward_returns.py:48`
- `golden_vector/lab/forward_returns.py:52`

The plan says `bench_fwd_simple` is exactly recoverable as `stock_fwd - alpha` in log space, but the
planned persisted field is `stock_fwd_simple`, not `stock_fwd_log`. A future implementation could
accidentally subtract log alpha from a simple return.

Concrete fix:
- Either also persist `stock_fwd_log`, or write the recovery formula explicitly as
  `bench_fwd_simple = exp(log1p(stock_fwd_simple) - alpha) - 1`.
- Add a round-trip test against the existing forward-return panel columns.

### LOW - The proposed serve guard forbids useful persisted field names

Where:
- `reviews/codex/claude_capture_behavior_engine_plan.md:365`
- `tests/test_lab_page.py:291`
- `tests/test_workspace_app.py:2474`

The plan proposes forbidding tokens such as `peer_percentile`, `down_capture`, `up_capture`, and the
archetype literals in serve modules. Banning compute functions and aggregation methods is good. Banning
persisted column names can make the render code harder to read and can encourage indirect lookups that
are harder to test.

Concrete fix:
- Forbid compute helpers/operators in serve: `mann_kendall`, `theil_sen`, `.mean(`, `.groupby(`,
  `.rank(`, `/ mean(`, etc.
- Allow persisted field names inside typed data structures and renderer constants.
- Add render-level tests with known persisted capture/archetype values proving serve echoes them
  without recomputing them.

### LOW - Peer snapshot survivorship bias needs to constrain the headline, not only peer trend

Where:
- `reviews/codex/claude_capture_behavior_engine_plan.md:154`
- `reviews/codex/claude_capture_behavior_engine_plan.md:264`
- `reviews/codex/claude_capture_behavior_engine_plan.md:266`
- `reviews/codex/claude_capture_behavior_engine_plan.md:374`

The plan correctly defers peer trend because the miner universe is survivor-only. The same bias still
affects all-history peer snapshot medians and top/bottom quartile rates for old episodes, because
failed miners are missing from those historical peer pools.

Concrete fix:
- Keep the peer snapshot descriptive, survivor-only, and visibly caveated.
- Prefer recent/decay peer snapshot values over all-history values as any headline.
- Stamp `survivor_universe=true` and a `peer_snapshot_status`/`caveat` on the artifact.

## Positive Checks

- The plan is correct that `fwd_log_ret_{h}w` already exists and is currently dropped before episode
  persistence (`golden_vector/lab/forward_returns.py:48`, `golden_vector/lab/conditional_dial.py:449`).
- A schema bump from v3 to v4 is appropriate for adding the miner's own forward return
  (`golden_vector/lab/conditional_dial.py:86`, `golden_vector/lab/conditional_dial.py:375`).
- Reusing/lifting `weighted_median` instead of importing `model/` from `lab/` is the right dependency
  direction.
- The plan keeps analytics in Lab builders and leaves serve as render-only; that matches the repo's
  data-spine rules.
