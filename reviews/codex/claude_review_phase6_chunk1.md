# Claude review — Phase 6 chunk 1 (#25 score-note, #27a option-policy config, #23 IV cap)

**Reviewer:** Claude Code (Opus 4.8), first-hand (read the staged diffs for `sensitivity_ranking.py`, `option_signals.py`, `options_liquidity.py`, `config_models.py`, `hedge_readiness.yaml`, `candidate_puts.py` + tests) plus an adversarial verification sweep (14 agents, every finding re-checked against the code; one self-finding correctly refuted).
**Scope:** Codex's staged chunk-1 of Phase 6 — items #25, #27a, #23. 509 insertions, 11 files.
**Suite:** **876 passed, 0 failures.**

## Verdict: **READY WITH CHANGES** — do not commit until M1 + M2 land.

The crux of #23 (flag-not-drop) is correctly implemented and the work is strong. But two plan-level MEDIUMs are real and belong *in this chunk* (both are part of #23/#27a), so they should be fixed before I commit the checkpoint.

## FOR CODEX — action required
Fix these before this chunk is committed, in order (full detail in **Findings** below):
1. **M1** — restore the lottery-warning trigger: add config field `option_lottery_implied_volatility_threshold` (default **0.75**), validate `≤ option_extreme_implied_volatility_threshold` and inside the IV hard bounds, use it in `_contract_is_lottery_like`, and add a test pinning that an IV~1.0 short-DTE low-delta put **is** `lottery_like`.
2. **M2** — finish #27a: migrate the implied-vs-modeled verdict thresholds (`header_context.py:24-25`, `1.5` / `0.67`) into validated config (`option_verdict_model_over_market_ratio`, `option_verdict_market_over_model_ratio`), validate `model_over_market > 1 > market_over_model > 0`, thread into `_verdict()` via `app_config`, add accept/reject tests.
3. **N1** — bump `HedgeReadinessConfig.version` 1 → 2 and `hedge_readiness.yaml` `version: 2`.

Optional (do not block commit): **M3** (flag the CLI grid path) + **N2–N4** — the primary web UI already flags correctly; these are secondary surfaces + nits.

**Then:** leave everything staged, ping Claude — Claude verifies the deltas and commits. Do not commit yourself. Do not touch `candidate_finder.py` / `tool_a` / `tool_c` / lenses (the #25 scope must stay narrow).

## What's strong (verified first-hand)
- **#23 crux correct.** A wide hard-drop band (`candidate_min/max_implied_volatility = 0.01..10.0` → `unusable_iv`) with a **soft flag band inside it** (`option_extreme_implied_volatility_threshold = 3.0` → `extreme_iv`, + `lottery_like`). A high-but-plausible-IV contract (e.g. 4.0) is **kept and flagged**, not dropped, across candidate selection + the signal chart frames. The hardcoded `0.01<=iv<=3.0` at `option_signals.py:341` is gone. Tests pass for the *right* reasons (the IV-4.0 signal-frame test uses DTE 74 / |delta| 0.25 so it genuinely survives the filter; IV-12.0 drops as `unusable_iv`).
- **#27a is a real migration, not cosmetics.** `settings_from_config` now passes 21 option-policy fields (OTM ranges, four bucket-gate triples, lottery params) that were previously *dead dataclass defaults* never wired from config. Strong cross-field validation (`config_models.py:303-353`): extreme threshold inside the IV hard bounds, ordered OTM bands, strict≤watch spreads, lottery delta ∈ (0,1]. Accept + reject tests for each.
- **#25 exactly scoped.** `is_rankable` now keys on `down_beta is not None` only; the note is verbatim ("score withheld; downside beta shown for context"); `score_eligible_count` stays honest (counts `is_rankable AND score_eligible`); `SensitivityRow` has **no** Tool A score field, so an ineligible ranked row cannot leak a score *by construction*. `candidate_finder.py`, `tool_a`, `tool_c`, lenses all confirmed unchanged.

## Findings

### MEDIUM — fix before commit

**M1 — The lottery-warning IV trigger was silently raised 4× (0.75 → 3.0); cheap speculative puts no longer flagged `lottery_like`.**
- `golden_vector/hedge/options_liquidity.py:1031-1044`. HEAD had a dedicated `lottery_iv_threshold = 0.75`; the patch deletes it and makes `_contract_is_lottery_like` gate on `extreme_implied_volatility_threshold` (= 3.0). So a short-DTE, low-delta gold-miner put with IV ~0.8–1.5 — the textbook cheap lottery ticket the flag exists to catch — is **no longer flagged**. The detail-panel "Lottery-like" note (`serve/detail_panels.py:627`) now effectively never fires in the realistic IV range. This is a user-facing speculation-warning regression bundled silently into a config migration, with no test pinning the chosen semantics. (Independently flagged in my first-hand read *and* the sweep.)
- **Fix:** add a separate config field `option_lottery_implied_volatility_threshold` (default **0.75**, validated `≤ option_extreme_implied_volatility_threshold` and inside the IV hard bounds) and use it in `_contract_is_lottery_like`. Add a test pinning that an IV~1.0 short-DTE low-delta put **is** `lottery_like`. (If consolidating onto 3.0 is genuinely intended, that's a product call for Emanuel — but the research brief explicitly wanted beginners steered away from lottery contracts, so the default should keep the ~0.75 trigger.)

**M2 — `#27a` is incomplete: the implied-vs-modeled verdict thresholds were not migrated to config.**
- `golden_vector/hedge/header_context.py:24-25` — `MODEL_GREATER_THAN_MARKET_RATIO = 1.5` and `MARKET_GREATER_THAN_MODEL_RATIO = 0.67` are still hardcoded module constants (consumed by `_verdict()` at lines 235/237). The plan's #27a verbatim lists *"…lottery thresholds, IV hard/soft bounds, **and the implied-vs-modeled verdict thresholds**"* — four of the five categories were migrated, this one was dropped. `header_context.py` isn't in the changeset at all.
- **Fix:** add `option_verdict_model_over_market_ratio` (default 1.5) and `option_verdict_market_over_model_ratio` (default 0.67) to `HedgeReadinessConfig` + `hedge_readiness.yaml`, validate `model_over_market > 1 > market_over_model > 0`, thread into `_verdict` via `app_config`, add accept/reject tests. (Or explicitly defer in the commit message so it isn't silently lost — but it's small, so just finish it.)

### Should-fix (low MEDIUM, leans NIT)

**M3 — The `candidate_puts.py` grid path keeps high IV but never sets the new flags.**
- `golden_vector/hedge/candidate_puts.py:384-406` — `_candidate_from_result` builds `OptionCandidate` without populating `quote_flags`, so with the cap at 10.0 an IV-4.0 put is now **kept but unflagged** in the CLI markdown report grid (`report.py:1131`) and the speculation section. So #23's "flag across **all** paths" is half-true here. **Mitigant:** the primary user-facing web Option Trading detail UI consumes the `options_liquidity` scan candidates, which **are** flagged (`serve/detail_panels.py:627`) — so the web surface is fine; the gap is the two secondary CLI surfaces (which don't render the flag today anyway).
- **Fix (low priority):** populate `OptionCandidate.quote_flags` in `_candidate_from_result` from a shared extreme/lottery helper (small extraction needed — the helpers are module-private to `options_liquidity.py`), or document that the CLI grid intentionally omits flags + add a test pinning the behavior.

### NITs (optional)
- **N1** — bump `HedgeReadinessConfig.version` 1 → 2 (21 new fields; repo convention bumps on schema change; `config_hash` already captures drift, so hygiene only). `config_models.py:104` / `hedge_readiness.yaml:1`.
- **N2** — `candidate_max_implied_volatility: 10.0` (1000% IV) is a very loose corrupt-only ceiling; add a one-line comment that it's the corrupt-data ceiling (not a tradability gate) and consider whether ~5.0 better matches "obviously corrupt." Optional boundary test at IV~9.5.
- **N3** — `_chart_liquidity_flag`'s `unusable_iv` branch is unreachable for signal frames (they're pre-filtered to usable IV) — drop it with a comment, or leave as defensive. `option_signals.py:807-816`.
- **N4** — `skew_curve` `quote_flags` column emits real `None` for unselected slots vs `''` elsewhere; no consumer yet and pandas `.str.contains` does **not** raise on None (the sweep's "could raise" was refuted), so cosmetic — normalize to `''` + a column-schema test (also satisfies the plan's chart-frame column-test ask). `option_signals.py:773`.

### Refuted (logged for honesty)
- A sweep finding claimed the #25 test "no longer asserts the ineligible row's rank is a real integer." **Refuted** — the test asserts `rows[0]` is BAD (the ineligible name) **and** `rows[0].rank == 1`, which together prove it. No change needed.

## Recommended order for Codex
1. **M1** — separate `option_lottery_implied_volatility_threshold` (default 0.75) + pinning test. *(restores the lottery warning)*
2. **M2** — migrate the two verdict-ratio thresholds to validated config + thread + tests. *(completes #27a)*
3. **N1** — bump the config version to 2.
4. **M3** + N2/N3/N4 as convenient (M3's web surface already works; these are polish).

Once M1 + M2 (+ N1) land and the suite is green, I'll verify the deltas first-hand and commit the chunk.
