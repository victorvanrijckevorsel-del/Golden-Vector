# Claude review — Codex option snapshot fallback plan (2026-06-11)

Reviewed: `reviews/codex/codex_option_snapshot_fallback_plan.md`
Verdict: **APPROVE WITH CHANGES** — the architecture (one manifest, freshness domains, backend-resolved carry-forward, quality gates untouched) is right. But the plan misses the one integration that makes or breaks the feature: the existing alignment machinery will mark every carried-forward publish as `WARN`/`incomplete` and push scary mismatch warnings into both Candidate Finder and the ticker report. That integration is finding H1 below. I have applied all changes directly to the plan file and answered the five review questions at the bottom of it.

## What I read first-hand

- `golden_vector/cli.py:1596-1738` (`run_option_artifacts`, `_previous_option_contract_metrics`) and `:2900-3123` (refresh orchestration, portfolio step, manifest publish)
- `golden_vector/app/model_state.py` (entire file — manifest build, `_artifact_map`, `_alignment`, `summarize_model_state_alignment`, resolvers, immutable-path logic)
- `golden_vector/hedge/option_signals.py:395-445` (`_data_quality_label`), `:860-896` (`_publish_blockers`), history load/persist
- `golden_vector/serve/option_trading_data.py:496-630` (manifest-resolved artifact reads, sha256 verify, stale-schema error, alignment warnings)
- `golden_vector/serve/candidate_finder_data.py:563-697` (`_alignment`)
- `golden_vector/hedge/report.py:1255-1317` (`_context_alignment`)
- `golden_vector/contracts/option_artifacts.py` (names, required subset, schema version)
- `golden_vector/app/market_hours_refresh.py` (existing market-hours decision helper)
- `golden_vector/app/run_pruning.py:53-99` (manifest-referenced path protection)

## Verified code facts the plan builds on

1. The blocker exit happens **before** any artifact is persisted (`cli.py:1659` vs `:1687`). On a blocked day, disk still holds the previous good run-stamped artifacts, the previous latest aliases, AND the previous manifest with their paths + sha256s. Carry-forward inputs already exist; nothing needs to be "preserved" extra.
2. A blocked option step also aborts the **portfolio** step (runs after option-artifacts, `cli.py:3061-3079`) and the manifest publish. The fix un-blocks portfolio too — added to acceptance criteria.
3. The manifest builder records sha256, schema_version, row_count, and immutable run-stamped paths for every option artifact on every publish (`model_state.py:563-631`). The previous manifest is therefore a complete, verifiable carry-forward source.
4. The serve reader requires **all ten** `OPTION_ARTIFACT_NAMES` to resolve through the manifest, verifies sha256 per file, and fails loud on stale schema (`option_trading_data.py:522-549`). A partial carried set would crash the page, not degrade it.
5. Both Candidate Finder and the ticker report use `summarize_model_state_alignment` as **authoritative when it returns a verdict** and only fall back to local run-id comparisons when it returns `None` (`candidate_finder_data.py:596-626`, `report.py:1265-1278`). One function controls the whole warning story.
6. Run pruning protects every artifact path referenced by every retained model-state manifest (`run_pruning.py:60-62`). A new manifest that references old option files automatically protects them. No new pruning work needed — just a regression test.
7. `MODEL_STATE_MANIFEST_VERSION` is written but never read-gated anywhere (`model_state.py:36,256,980`). `freshness_domains` is purely additive; no version bump required.
8. Each option artifact frame already embeds `options_as_of_date` and run ids (`option_artifact_frames.py:313`) — the freshness box date needs no new storage.
9. `run_context.finalize` already records `option_signal_publish_blockers` on blocked runs (`cli.py:1661-1672`) — Phase 6 diagnostics are an enrichment of an existing payload, not a new file.

## Findings

| # | Sev | Finding | Evidence | Resolution applied to plan |
|---|-----|---------|----------|-----------------------------|
| H1 | HIGH | Plan never addresses `alignment`/`state` semantics. `_alignment` compares the four required option artifacts' `snapshot_refresh_run_id` against **today's** options ingestion run id; carried-forward artifacts carry yesterday's id → `WARN` → `state=incomplete` → authoritative scary warnings in Candidate Finder, ticker report, and status page. The freshness box would sit next to contradictory mismatch warnings. | `model_state.py:806-811, 249-253`; `candidate_finder_data.py:596-626`; `report.py:1265-1278` | New "Alignment integration" subsection: under CARRIED_FORWARD, `_alignment` validates the carried set against its **own** source run id (self-consistency still checked), emits no mismatch warnings, `state` stays `complete`. Both consumers then stay calm with zero changes to their authoritative-path logic. |
| H2 | HIGH | Phase 2 reads like a new scanner/resolver module. The chain already exists: previous manifest entries (path, sha256, schema_version, row_count) + `resolve_current_model_artifact_path` (immutable+usable+exists checks) + the serve-side sha256 verify pattern. `_previous_option_contract_metrics` (`cli.py:1734-1738`) is the existing precedent. | `model_state.py:96-128`; `option_trading_data.py:562-581` | Phase 2 rewritten to name the concrete implementation: small functions in `app/model_state.py` that load the previous manifest and re-verify entries. No new module. |
| M1 | MED | `FAILED` cannot occur as a *manifest* freshness status — hard failures abort the refresh before publish, so no manifest is written. Keeping it in the manifest contract invites dead code and confusion. | `cli.py:3048-3056` | Manifest statuses reduced to `OK / CARRIED_FORWARD / UNAVAILABLE`; `FAILED` kept as a run/CLI outcome only. |
| M2 | MED | "Fail only because of publish blockers" must be classified structurally, not by matching `SPARSE`/`STALE_QUOTES` strings out of messages. The blocked case is precisely "build succeeded and `publish_blockers` is non-empty" (`cli.py:1659`); everything else (missing sources `:1614`, exceptions `:1716`) stays hard. | `cli.py:1596-1733` | Phase 3 now requires a structured outcome (OK/BLOCKED(blockers)/FAILED) returned from the build step; exit codes mapped only at the CLI boundary; standalone `option-artifacts` keeps a non-zero exit when blocked. |
| M3 | MED | Phase 4 carried-forward example asserts "US options are currently closed" — the backend can't know that from blockers alone (GDX=SPARSE can happen during market hours on a bad feed day). | plan §Phase 4; `market_hours_refresh.py:31-56` | Message is now conditional: market-closed phrasing only when `market_hours_refresh_decision` says outside-hours; otherwise quote the blockers. Helper used for message context only, never to gate. One shared backend formatter for all four surfaces (Option Trading, detail lens, Candidate Finder, `status`). |
| M4 | MED | Q2 ambiguity is actually settled by the reader contract: all ten names must resolve or the page raises/returns nothing (`option_trading_data.py:525-534`). Since one run persists all ten atomically (`persist_option_artifacts.py:29-34`), requiring all ten from the same source run is free. | `option_trading_data.py:522-549` | Carry-forward rule: all ten present + sha-verified + same source run + current schema version; the four `REQUIRED_OPTION_ARTIFACT_NAMES` additionally non-empty; otherwise `UNAVAILABLE`. |
| M5 | MED | Test list missing the regressions that protect this feature long-term: multi-day chain stability, same-day second refresh, pruning protection, no history append on blocked days, previous-manifest-incomplete edge, schema-bump downgrade. | `run_pruning.py:60-62`; `cli.py:1692` | Phase 7 extended with tests 10-15. |
| L1 | LOW | Domain key `options` collides with the existing `artifacts.options` entry (the options **ingestion manifest**, which IS fresh on a carried day — chains were fetched, quotes were stale). | `model_state.py:502-533` | Domain key renamed `option_artifacts`; redundant `parent_refresh_id` dropped from the `core` domain example. |
| L2 | LOW | Phase 6 proposes a new diagnostic file; the run-context summary already captures blockers and is retained/pruned by existing policy. | `cli.py:1661-1672` | Phase 6 folded into enriching the existing run-context summary payload. |
| L3 | LOW | Plan doesn't mention that the blocked option step currently also blocks the portfolio step — un-blocking it is part of the user-visible win and needs an acceptance criterion. | `cli.py:3061-3079` | Added to Problem + Acceptance Criteria. |
| L4 | LOW | UNAVAILABLE semantics unspecified: with required option artifacts missing, `state` will be `incomplete` (truthful) and `summarize_model_state_alignment` returns `None` (OK + not-complete), so readers fall back to local checks and show generic "Missing refresh ids" messages. | `model_state.py:335-336`; `candidate_finder_data.py:639-652` | Plan now states: keep `state=incomplete` for UNAVAILABLE; pages prefer the `freshness_domains` message over generic fallbacks. |

## Answers to Codex's five questions

**Q1 — One manifest with freshness domains, or a separate options pointer?**
One manifest. Three reasons grounded in the code: (a) every reader already resolves through this single manifest (`option_trading_data.py:522`, `candidate_finder_data.py:120`) — a second pointer reintroduces the split-brain problem the manifest was built to kill; (b) pruning protection is derived from retained manifests (`run_pruning.py:60-62`), so a separate pointer would need its own protection plumbing or risk its files being pruned; (c) the alignment summarizer that both tools treat as authoritative reads this manifest — a second pointer would bypass it.

**Q2 — Mandatory carry-forward set: required four or all ten?**
All ten `OPTION_ARTIFACT_NAMES`, from the same source run, sha-verified, current schema version — because the serve reader requires all ten to resolve or it fails (`option_trading_data.py:525-534`), and one build persists all ten together so this costs nothing. The four `REQUIRED_OPTION_ARTIFACT_NAMES` must additionally be non-empty (mirrors the existing zero-row health warnings). Anything less → `UNAVAILABLE`, never a partial carry.

**Q3 — Are SPARSE / LOW_LIQUIDITY / STALE_QUOTES all carry-forwardable?**
Yes, plus `NO_BENCHMARK` and the empty-summary "benchmark rows are missing" case. Every label `_data_quality_label` can produce (`option_signals.py:409-426`) is a verdict about market data quality right now — exactly what carry-forward is for. None of them indicates code or schema damage. The hard-fail set is everything that bypasses the blocker check: missing options manifest, exceptions during build/persist, schema corruption. Critically: classify by code path (build succeeded + `publish_blockers` non-empty), never by parsing blocker strings.

**Q4 — Where does the resolver live?**
`app/model_state.py`. The carry-forward decision is manifest-to-manifest logic, and everything it needs is already in that module: previous-manifest loading, the immutable/usable artifact resolution rules, sha256 helpers, `_alignment`, and the publish path that must record the freshness domain. A new `artifact_freshness.py` would split the manifest brain across two files (our avoid-duplication rule), and `hedge/option_artifact_sources.py` is build-input territory — the wrong layer for publish decisions.

**Q5 — Skip pre-market via market-hours detection, or always attempt and classify?**
Always attempt, then classify. The option-artifact step is pure local compute — chains were already fetched by update-data (`load_option_artifact_source_inputs` reads local files, `cli.py:1613`) — so attempting costs seconds and the blockers are ground truth. A calendar gate can false-skip (half-days, holiday drift, a fine snapshot at 09:50 ET) and can never know quote quality. Use the existing `market_hours_refresh_decision` helper only to enrich the recorded reason and the user-facing message ("likely closed" vs "quotes not publishable"). Scheduled runs are already gated by the separate `market-hours-refresh` command, which is the right place for time-based gating.

## Bonus property worth knowing

Because carry-forward sources from the previous **manifest** (not from "yesterday"), a second refresh on the same day naturally carries this morning's good 09:40 snapshot, and a multi-day outage chains while preserving the original `source_run_id` and `as_of_date` from the artifact entries themselves. No special casing for either — but both are now pinned by tests 10-11.
