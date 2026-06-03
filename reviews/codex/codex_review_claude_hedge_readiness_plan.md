# Review: Hedge Readiness Plan

**Grade: NEEDS CHANGES**

The user-value framing is much stronger than the earlier raw options-ingestion idea. The plan now answers real decisions: direct hedgeability, candidate puts, premium versus modeled downside, and proxy paths for non-optionable names. I would not start implementation yet because a few plan details would force either silent scope decisions during coding or a replay/audit gap.

## Risk 1: 25-delta interpolation

The plan has three slightly different rules: "interpolate to the strike" in the candidate grid (`reviews/codex/claude_hedge_readiness_plan.md:188`), `strike_for_target_delta` returning a target-delta result (`reviews/codex/claude_hedge_readiness_plan.md:268`), and then snapping back to a real listed strike for trade fields (`reviews/codex/claude_hedge_readiness_plan.md:440`). For a user-facing hedge shortlist, the listed contract should be canonical. Report the real listed strike whose computed delta is closest to -0.25, with a `delta_gap` or "target delta unavailable" flag if needed. A theoretical interpolated strike is useful for analytics, but mixing it with snapped bid/ask/OI will make the row look more precise than it is.

## Risk 2: Missing Yahoo IV

The plan correctly says to trust Yahoo IV and flag nulls (`reviews/codex/claude_hedge_readiness_plan.md:73`), but the fallback policy in risk 2 is still undecided (`reviews/codex/claude_hedge_readiness_plan.md:550`). Do not estimate IV from mid-quotes in M1. That adds a numerical solver, more edge cases, and false precision exactly where quotes are already weak. If IV is missing, delta and 25-delta IV should be null for that contract; the report can still show bid/ask/OI as quote context. If a ticker has quotes but no usable IV near the target, fall back to a nearest-OTM contract only if the row is clearly labeled "delta unavailable."

## Risk 3: Implied move on thin chains

The implied-move feature should be liquidity-gated before it is shown as a signal. The plan computes `(ATM put mid + ATM call mid) / underlying` (`reviews/codex/claude_hedge_readiness_plan.md:156`, `reviews/codex/claude_hedge_readiness_plan.md:325`), but thin miners can have stale or crossed quotes. Add contract-level gates before reporting implied move: positive bid/ask, maximum spread percent, minimum OI or volume, and same-expiration call/put availability. These thresholds belong in `config/hedge_readiness.yaml`, which the plan already introduces for other bands (`reviews/codex/claude_hedge_readiness_plan.md:209`, `reviews/codex/claude_hedge_readiness_plan.md:511`).

## Risk 4: `update-data` runtime

Best-effort per-ticker failure is right, but making options a mandatory part of every `update-data` run is still a product/runtime decision, not just an engineering detail (`reviews/codex/claude_hedge_readiness_plan.md:392`). Current `update-data` is the foundation refresh path (`golden_vector/cli.py:338`), and adding 64 option probes plus chain downloads can make normal refresh slower and more failure-prone. Keep the default if Emanuel wants daily options, but add a CLI escape hatch such as `--skip-options` or `--options/--no-options`, with the run summary saying whether options ran. That preserves the locked cadence without trapping every future market-data refresh behind options availability.

## Risk 5: Proxy similarity

Down-beta-only proxy matching is not sufficient as a confidence claim (`reviews/codex/claude_hedge_readiness_plan.md:213`). Two names can have similar `down_beta_core` but very different residual behavior, geography, currency exposure, or liquidity. Tool B verdict should not disqualify a proxy, because a proxy hedge is about traded behavior, not whether the proxy company is fundamentally attractive. But Tool B verdict and Tool A confidence should be displayed as context, and a down-beta-only proxy should carry an explicit basis-risk label. If pairwise return correlation is too much for M1, call the method "down-beta similarity" rather than "behaviorally similar."

## Risk 6: GDX/GDXJ placement

This is blocking because the plan leaves the benchmark location undecided (`reviews/codex/claude_hedge_readiness_plan.md:554`). Do not put GDX/GDXJ into `config/universe.yaml` with `is_benchmark: true`: the config model forbids unknown fields (`golden_vector/contracts/config_models.py:14`), and the foundation registry treats active Tool A/B universe tickers as normal model inputs (`golden_vector/ingestion/registry.py:128`). Adding benchmarks there risks polluting Tool A/B or breaking config validation. Put benchmarks in `config/hedge_readiness.yaml` or a separate `config/benchmarks.yaml`, fetch them through a dedicated hedge/options path, and keep them out of Tool A/B eligibility unless a later plan explicitly changes that contract.

## Risk 7: Report output

Stdout is fine for quick use, but the canonical report should be written under `data/output/hedge_readiness/` with a run-id/date file and a latest alias. The plan already worries about readability (`reviews/codex/claude_hedge_readiness_plan.md:555`), and a file output also gives Emanuel something stable to compare, attach to reviews, and audit. Print the path plus a compact summary to stdout. This requires adding an `output_hedge_readiness_dir` path, which is not currently in the target path list (`reviews/codex/claude_hedge_readiness_plan.md:103`).

## Additional Findings

1. **Replay/provenance is not actually satisfied.** The acceptance criterion says the replay manifest "auto-captures the run's options snapshot paths" (`reviews/codex/claude_hedge_readiness_plan.md:528`), but the current replay manifest only snapshots configs/manual data/foundation manifest (`golden_vector/app/replay_manifest.py:62`). `RunContext.record_artifact()` records artifact paths in `metadata.json`, not in `replay_manifest.json` (`golden_vector/app/run_context.py:96`, `golden_vector/app/run_context.py:118`). Because the plan also overwrites same-day options files (`reviews/codex/claude_hedge_readiness_plan.md:71`), a second same-day run could destroy the exact options input for the first run. Add run-local options snapshots under `data/runs/<run_id>/snapshots/` or explicitly extend replay manifest capture before implementing.

2. **The raw schema is not raw and conflicts with step order.** The raw options-chain schema includes `delta` (`reviews/codex/claude_hedge_readiness_plan.md:139`), but Black-Scholes is not added until step 2 (`reviews/codex/claude_hedge_readiness_plan.md:505`) and raw chain fetching is step 1 (`reviews/codex/claude_hedge_readiness_plan.md:504`). More importantly, delta is a derived feature, not a Yahoo raw-chain field. Keep raw snapshots to Yahoo fields plus simple snapshot metadata; put delta in the features/candidate layer.

3. **The report reads a `latest.parquet` that the storage layout never creates.** The report module spec says it reads `data/raw/options/<TICKER>/latest.parquet` (`reviews/codex/claude_hedge_readiness_plan.md:368`), but the storage layout and persist function write only `data/raw/options/<TICKER>/<YYYYMMDD>.parquet` (`reviews/codex/claude_hedge_readiness_plan.md:69`, `reviews/codex/claude_hedge_readiness_plan.md:242`). Decide whether there is a latest alias, a manifest pointer, or "latest by filename" lookup before implementation.

4. **Holdings file creation is inconsistent.** The module layout says `data/manual/holdings/holdings.yaml` is "created at runtime if missing" (`reviews/codex/claude_hedge_readiness_plan.md:106`), while the loader spec says missing file returns an empty list and does not error (`reviews/codex/claude_hedge_readiness_plan.md:297`). Prefer no implicit creation during report reads; if an example file is needed, make it a fixture or docs example.

## Bottom Line

The product direction is good, but the plan needs one revision before coding: lock the benchmark config location, fix replay-safe options retention, separate raw from derived schema, and decide the latest/report output paths. After that, I expect this to be READY or READY WITH MINOR CHANGES.
