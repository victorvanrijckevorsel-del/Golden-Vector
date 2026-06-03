# Review: Claude Tool C/D Plan

**Grade: NEEDS CHANGES**

The direction is right: Tool C and Tool D are framed as decision rankings, not raw options plumbing, and they avoid duplicating Tool A/B analytics. The plan is not ready to implement because two input assumptions do not match the current repo state: benchmark snapshots from M1 are not wired through yet, and there is no published weekly-return artifact at the path the plan names. Fix those before step 1 so the implementation does not build around phantom data sources.

## Risk 1: Tail Confidence Thresholds

The proposed `min_events` approach is directionally fine, but the plan should make event counts metric-local, not tool-global. The plan defines tail metrics over worst 10% and 20% gold weeks (`reviews/codex/claude_tool_c_d_plan.md:150`, `reviews/codex/claude_tool_c_d_plan.md:329`) and asks whether low/medium/high confidence bands are right (`reviews/codex/claude_tool_c_d_plan.md:454`). That is only safe if the final row carries the actual usable event count after ticker/gold/benchmark alignment, because `rel_weakness_vs_gdx_pct` can have a different event count than `tail_avg_return_worst10pct`. Use the count that survived each metric's data intersection; otherwise a ticker can look "high confidence" on the gold-only metric while the benchmark-relative metric is based on a thinner slice.

## Risk 2: Per-Ticker Weekly Returns Source

This is a blocker. The plan assumes per-ticker weekly returns already exist in `data/intermediate/usd_equities/<run>.parquet` or an equivalent intermediate (`reviews/codex/claude_tool_c_d_plan.md:68`, `reviews/codex/claude_tool_c_d_plan.md:455`), but the current pipeline publishes daily normalized equities as per-ticker intermediate files and a run-local `snapshots/usd_equities.parquet` (`golden_vector/ingestion/persist.py:102`, `golden_vector/ingestion/persist.py:115`, `golden_vector/ingestion/persist.py:121`). The stable loader is `load_latest_foundation_snapshot`, which resolves `normalized_equities_snapshot_path` from the latest foundation manifest (`golden_vector/app/latest_data.py:57`, `golden_vector/app/latest_data.py:77`, `golden_vector/app/latest_data.py:121`). Tool C needs the plan to say explicitly whether it resamples those daily histories to weekly, or whether a new weekly helper/artifact is part of M2.

## Risk 3: GDX/GDXJ History Coverage

This is also a blocker in the current branch. The plan says GDX/GDXJ are already fetched in M1 and will live under run-local benchmark snapshots (`reviews/codex/claude_tool_c_d_plan.md:16`, `reviews/codex/claude_tool_c_d_plan.md:70`, `reviews/codex/claude_tool_c_d_plan.md:456`), but the repo currently has benchmark config and fetcher support, not an update-data phase that persists benchmark histories into `data/runs/<run_id>/snapshots/benchmarks/*.parquet`. The existing path surface has `benchmarks_dir` and `latest_options_manifest_path` (`golden_vector/app/paths.py:167`, `golden_vector/app/paths.py:187`), and options persistence writes option manifests (`golden_vector/ingestion/persist_options.py:78`), but Tool C cannot rely on benchmark snapshots until M1 actually wires and captures them. Either make M2 explicitly depend on completed M1 benchmark persistence, or define a current-state fallback where benchmark-relative fields are skipped with clear missing-input tags.

## Risk 4: Negative Current Margin

The plan correctly calls negative margin a signal rather than an error (`reviews/codex/claude_tool_c_d_plan.md:370`, `reviews/codex/claude_tool_c_d_plan.md:388`, `reviews/codex/claude_tool_c_d_plan.md:457`). The missing piece is output semantics for percentage-change fields: if current EBITDA is zero or negative, `ebitda_pct_change_minus10` and `ebitda_pct_change_minus20` should be null and tagged, not computed as misleading positive/negative percentages. This is not a design blocker, but it needs to be specified before coding because it affects schema, tests, and the risk-tag list.

## Risk 5: Tool D And Tool B Verdict Context

Keeping `SCREEN_OUT` as context rather than a disqualifier is the right call; a weak business can still be a useful fragility warning. The plan says that in the schema section (`reviews/codex/claude_tool_c_d_plan.md:48`, `reviews/codex/claude_tool_c_d_plan.md:212`, `reviews/codex/claude_tool_c_d_plan.md:458`), but later says Tool D eligibility is based on "Tool B's screening_verdict != error" (`reviews/codex/claude_tool_c_d_plan.md:392`). Tighten this into one rule: Tool B verdict is display context, while Tool D rank eligibility is driven by the Tool D inputs needed for each component. The existing manual-data loader is read-only and returns the screening inputs Tool D needs (`golden_vector/screening/manual_data.py:51`, `golden_vector/screening/manual_data.py:70`), so there is no need to infer data eligibility from the business verdict.

## Risk 6: Net Debt / EBITDA Division By Zero

The plan identifies the divide-by-zero/sign problem (`reviews/codex/claude_tool_c_d_plan.md:459`), but the Tool D schema and tag list do not yet include an explicit tag for nonpositive stress EBITDA (`reviews/codex/claude_tool_c_d_plan.md:181`, `reviews/codex/claude_tool_c_d_plan.md:187`, `reviews/codex/claude_tool_c_d_plan.md:191`). This should be resolved in the plan, not left to implementation taste: when EBITDA is zero or negative, leverage ratios should be null, and a tag such as `stress_ebitda_nonpositive` or `leverage_undefined_under_stress` should explain why. Do not emit infinity, negative leverage, or a rank contribution from an undefined ratio.

## Risk 7: Eligibility Intersection Logic

Independent eligibility per tool is right, but the current statement is too broad (`reviews/codex/claude_tool_c_d_plan.md:215`, `reviews/codex/claude_tool_c_d_plan.md:392`, `reviews/codex/claude_tool_c_d_plan.md:460`). Tool C can inherit Tool A's `score_eligible`. Tool D should not inherit Tool A eligibility and should not disqualify on `SCREEN_OUT`; it should rank margin components when AISC, production, and spot gold are available, then separately suppress leverage components when debt or positive EBITDA is missing. That distinction matters because otherwise a missing debt field can wrongly remove a valid margin-stress signal, or a Tool B `SCREEN_OUT` can wrongly hide a company that is exactly the kind of fragile name Tool D should surface.

## Additional Findings

1. Replay/provenance is underspecified. The plan says `RunContext.start()` auto-captures provenance (`reviews/codex/claude_tool_c_d_plan.md:320`, `reviews/codex/claude_tool_c_d_plan.md:433`), but `RunContext.start()` alone does not record consumed Tool A/B parquet paths or the latest foundation snapshot used for Tool C. Existing CLI code explicitly captures foundation snapshots via `update_manifest_with_foundation` (`golden_vector/cli.py:1420`, `golden_vector/app/replay_manifest.py:96`), and options have a separate manifest updater (`golden_vector/app/replay_manifest.py:131`). Tool C/D need the same explicit source recording for replay to be useful.

2. The milestone text says all 64 names, while the plan's own current-state tables and completion report refer to 60 rows/tickers (`reviews/codex/claude_tool_c_d_plan.md:26`, `reviews/codex/claude_tool_c_d_plan.md:41`, `reviews/codex/claude_tool_c_d_plan.md:546`). This is not a blocker by itself, but the plan should avoid hard-coding 64 in tests or reports until the active universe and latest Tool A/B outputs actually contain 64.

3. The config step should explicitly add `tool_c.yaml` and `tool_d.yaml` to the central config loading contract. The plan adds the files and models, but the repo's config loader tracks expected config files centrally (`golden_vector/app/config.py:18`), and prior replay work hashes those configs. Missing that hook would make the commands run with partial provenance even if the computation is correct.

