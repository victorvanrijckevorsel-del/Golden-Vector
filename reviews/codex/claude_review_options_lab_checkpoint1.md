# Review — Options Liquidity Lab, Checkpoint 1 (Phase 1)

**Reviewer:** Claude Code (Opus 4.8), read-only review of the Phase 1 working tree.
**Verdict: APPROVE — continue to Phase 2.** The liquidity engine is clean, correct, and faithful to the v3 brief. One process item (commit the work) and two low-priority items below. No correctness bugs found.

## What I verified (by reading `golden_vector/hedge/options_liquidity.py`)
- **Tiers** (`_liquidity_tier`): invalid/≤0 bid|ask|mid → `no_trade`; `rel_spread` None or > watch (0.50) → `no_trade`; OI < min → `no_trade`; `rel_spread ≤ 0.20 AND mid ≥ 0.15` → `tradable`; else `watch`. Matches the brief; invalid quotes are never scored as usable. ✅
- **Liquidity score**: `0.55*spread + 0.25*OI + 0.10*premium + 0.05*depth + 0.05*volume`, spread-dominant, volume minimal — exactly v3. ✅
- **Sensible-moneyness gate**: `|strike−spot|/spot ≤ 0.35`. The **AEM strike-50 on a $175 stock = 71% → rejected** (not usable), shown as a near-miss for context. The core failure the whole redesign was about is fixed. ✅
- **Shared `is_usable_candidate()`**: `bucket_fit AND tier==tradable AND moneyness ≤ max AND IV usable` — the single primitive the Candidate Finder will reuse. ✅
- **Buckets**: puts get most_liquid/near_atm/directional/tail/model_fit; calls drop tail (correct). Delta ranges per research (calls 0.35–0.50, dir puts −0.50/−0.35, tail −0.30/−0.15). Model-fit anchored to `spot×(1+beta×gold_move)`. ✅
- **Never force a candidate**: no metrics → "no chain"; nothing usable → `rejected` slot with the best near-miss + an honest reason. ✅
- **Monthly preference** (3rd-Friday detection) used in the sort tiebreak. ✅
- **Back-compat**: every new `OptionCandidate`/`OptionCandidateSlot` field is defaulted, so the M1.5 report/scenarios/sensitivity paths that build `OptionCandidate` the old way still work (584 tests pass confirm). ✅
- **Config**: the `option_liquidity_*` / `option_dte_bands` / `option_sensible_moneyness_max_pct` fields exist on `HedgeReadinessConfig` with sensible defaults + in the YAML, consumed via a clean `Protocol`. ✅

## Findings

### P-1 (Process) — Phase 1 is uncommitted as one big working-tree blob
The last commit is `86ed1cf Fix shipping safety review findings`; the entire options-liquidity lab (new `options_liquidity.py` + ~17 modified files + 3 new test files) is **uncommitted**. The brief asked for one commit per step. **Commit Phase 1 before Phase 2** — ideally as a few logical commits (engine + config; data/UI rewiring; CLI; tests) so it's reviewable and revertible. Also run the self-cross-check on the diff: confirm `black_scholes.py`, `report.py`, and `speculation_section.py` changes are *intended* Phase-1 ripples (e.g. `OptionCandidate` field additions) and not stray edits — explain each in the commit message.

### L-1 (Low, perf) — `near_spot_depth` is O(N²) per scan
`_near_spot_depth_count` re-filters the full frame and iterates the expiry/side subset **once per contract**. On a large chain (~thousands of rows) that's quadratic. It's cached per refresh so steady-state is fine, but precomputing depth once per `(expiration, side)` would make the first scan snappier. Not blocking.

### L-2 (Low) — confirm validators + the OI floor note
Confirm the new float/int config fields have positivity/range validators (consistent with the rest of `HedgeReadinessConfig`). And keep the brief's note that the **Tradable OI floor (currently 1)** is a candidate for empirical tightening once we see GDX/miner data — fine as-is for now.

### Nit — `metric` reused as a comprehension variable
In `_slot_for_bucket`, `tradable_contract_count=sum(1 for metric in metrics ...)` reuses `metric`. Python scopes the comprehension variable so there's **no bug**, but renaming it (e.g. `m`) reads cleaner.

## On the data/UI (from the progress log + spot checks)
The overview is trimmed to the Phase-1 columns; the detail panel is bucket/horizon rows with tiers, spread + half-spread cost, Yahoo expiry links, and Select only for usable contracts; the refresh placeholder is disabled (no implied live quotes); the `options-liquidity-summary` CLI works. This matches the brief. I'd confirm at Checkpoint visual review that an all-thin ticker shows "No sensible liquid contract" rows rather than anything that looks like a suggestion.

## Bottom line
Phase 1 is genuinely good — the engine is the right shape, the junk-rejection works, the shared primitive is in place, and nothing downstream is broken. **Commit it (P-1), then proceed to Phase 2** (ingest GDX/GDXJ option chains + surface them as liquid rows). The Candidate Finder can later build directly on `is_usable_candidate()` — exactly as intended.
