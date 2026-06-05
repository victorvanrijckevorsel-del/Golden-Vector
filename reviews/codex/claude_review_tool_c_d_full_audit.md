# Full Audit — Tool C + Tool D Build

**Reviewer:** Claude Code (Opus 4.8)
**Scope:** the entire Tool C + Tool D build, commits `bc99cd6..e8f126f` (16 commits, 33 files, +3,882/-18 over the Tool C/D range).
**Method:** read the critical math + integration files first-hand (`model/tool_d.py`, `model/tool_c.py`, `serve/candidate_finder_data.py`, `config/candidate_finder.yaml`) and ran four independent adversarial deep-dives (Tool C math, Tool D correctness, integration/regression, test quality). Findings below are cross-checked, not taken on trust.
**Overall grade: STRONG BUILD — SHIP AFTER 2 FIXES.** The six locked resolutions (L1–L6) are correctly implemented in the production code. There is **one genuine regression** (preset eligibility) and **one real crash path** (Tool C with empty Tool A) to fix, plus test-strengthening. Nothing here is a redesign.

---

## What's correct (verified first-hand — the reassurance)
All six locks hold in the shipped code:
- **L1 — Finder consumes spot Tool D only.** `_spot_tool_d_source` (`candidate_finder_data.py:708-733`) compares per-row `gold_price_used` vs `spot_gold_usd` (0.01 tolerance); a non-spot run blanks `tool_d_quality_rank` and warns; missing provenance columns are conservatively blanked. No per-lens gold dial exists. **Correct.**
- **L2 — stressed leverage = net_debt / forward_EBITDA(G), never Tool B's trailing column.** `tool_d.py:183` `_ratio(net_debt, forward_ebitda)` with `net_debt` from manual and `forward_ebitda` from the G-stressed Tool B frame; `_prepare_tool_b_latest` structurally drops everything except `ticker`+`source_run_id`, so a trailing `leverage` cannot leak in. EBITDA≤0 → null via `_ratio`/`_ev_ebitda` denominator guards — **never infinite. Correct.** Tool B is called twice (at G and at spot) as required.
- **L4 — quality rank = exactly 3 equal-weight components, FCF context-only, renormalized.** `_add_quality_scores` (`tool_d.py:233-258`) blends headroom/leverage/EV-EBITDA via `mean(skipna=True)`; `.where(notna().sum(axis=1).gt(0))` sets zero-component rows to NaN; FCF comes from the spot frame and never enters the score. **Correct.**
- **L5 — hit-rate thresholds from `config/tool_c.yaml`, event counts in output.** Confirmed thresholds flow config→model→`relative_behavior`; every relative/hit-rate/tail metric carries its own `_n` count. **Correct.**
- **L6 — `spot_gold_date` in schema and provenance.** In `TOOL_D_OUTPUT_COLUMNS`, in the row, and persisted to manifest metadata (`persist_tool_d.py`, `cli.py`). **Correct.**
- **Seams:** `oriented_percentile` is the single percentile implementation (reused, no duplicate); `build_structural_weekly_series` drives the weekly convention; Tool A `score_eligible` rows are masked **before** percentiles (not bottom-sorted after). **Correct.**
- **Backward-compat:** missing Tool C/D outputs degrade to an alignment **warning**, not a crash; `status`/`refresh`/`replay_manifest`/config-loading all tolerate old states; old manifests without Tool C/D sections still verify. **Correct.**

---

## Findings to fix

### H1 (High) — Adding Tool C/D to the two presets silently changes Candidate Finder results
`config/candidate_finder.yaml:145-195`: `bearish_put` and `bullish_call` each grew from **5 → 7** criteria (added `tool_c_*_rank` + `tool_d_quality_rank`). With `min_criteria_fraction: 0.67`, a row now needs ~5 of 7 present to stay rank-eligible.
- **When Tool C/D outputs are ABSENT** (any state before `tool-c`/`tool-d` have run — e.g. existing data, a partial refresh, or a C/D failure), those columns are NA for every ticker. Max present = 5; a ticker that previously qualified at **4/5 = 0.80** now sits at **4/7 = 0.57 < 0.67** and **silently drops off the screen**, even though its data is unchanged.
- **When Tool C/D are PRESENT**, the preset's composite score now blends the new percentiles, so prior ordering shifts. That's *intended* (the whole point of wiring them in), but there's **no parity test** documenting the change.
- This path is **untested** — the new tests cover the "missing → UNKNOWN warning" and NA-fill, but not the eligibility drop.
- **Why it matters:** the Candidate Finder is the highest-value existing surface. A universally-absent criterion should not penalize every ticker's eligibility.
- **Recommended fix:** exclude *selected criteria that are all-NA across the universe* from the present-fraction **denominator** (so a not-yet-run tool can't drop tickers), OR gate the three new criteria until C/D are a guaranteed part of every refresh. Either way, add a **parity regression test** pinning preset output with and without Tool C/D present. (Note: the standard `refresh` now runs A→B→C→D, so in the normal pipeline C/D will be present — this bites transitional/partial states, which is exactly when a silent change is most confusing.)

### H2 (Med→High, real crash) — Tool C raises `KeyError: 'score_eligible'` when Tool A input is empty/lacks the column
`tool_c.py:131-134` advertises a Tool-A-less fallback (`if base.empty: base = ticker-only from metrics`), but `_add_component_scores` (`:225`) and `_sink_ineligible_rows` (`:237`) then read `output["score_eligible"]` unconditionally, and `_ensure_columns` (`:140`) only seeds the component columns — not `score_eligible`. So **`tool-c` run when Tool A latest is missing/empty but metrics are computable → hard crash** instead of degraded output.
- **Why it matters:** running `tool-c` before `tool-a`, or against an empty Tool A frame, crashes rather than producing an empty/sunk result. It's an edge case (the happy path has Tool A), but it's a real, easily-triggered crash and the code explicitly claims to support that path.
- **Fix:** add `score_eligible` to `_ensure_columns(output, [...])` defaulting to `pd.NA` (consistent with `_truthy_score_eligible(None) → True`), or short-circuit to an empty/unranked frame when Tool A is absent. One line.

### M1 (Medium, test) — the L2 "ignores bogus Tool B leverage" test is partly theatrical
`tests/test_tool_d.py` injects `leverage = 999.0` into `tool_b_latest`, but that frame is column-stripped to `[ticker, source_run_id]` before Tool D ever sees it — so the decoy can't reach the code under test. The meaningful half of the assertion (`leverage_stressed == net_debt/forward_ebitda`) is fine, but the "999 is ignored" half proves nothing.
- **Fix:** inject the bogus `leverage` into the **stressed/spot Tool B frames that Tool D actually consumes** and assert the result still equals `net_debt/forward_ebitda(G)`. Then the test fails if anyone ever wires a trailing-leverage column into `_build_tool_d_row`.

### M2 (Medium, test gaps) — add the missing contract tests
Prioritized:
1. **L5:** compute relative behavior twice with *different* `downside_hit_rate_threshold` on identical data, assert the hit-rate output changes. (Today a hardcoded `-0.10` regression would pass — every test uses the default.)
2. **L4:** a Tool D row with all three quality components null → assert `tool_d_quality_rank` is **null** (not bottom-ranked); the Tool C analogue for a side with too few usable components.
3. **L1:** the "missing spot-gold provenance *columns*" branch (`candidate_finder_data.py:711-719`) — distinct from the "non-spot run" branch — is uncovered.
4. **Tool C:** a 3-ticker test proving an ineligible peer is *removed from the percentile pool* (not just sorted last) — i.e. an eligible row's rank is unchanged by the ineligible peer's presence.

### L1 (Low) — dead columns
`gold_regime.py:14-15,70-75` compute `gold_down_hit_event`/`gold_up_hit_event`, which nothing consumes (hit-rates are recomputed from *stock* returns in `relative_behavior`). Remove them or label them diagnostic-only — they invite future misuse (someone wiring the gold-side flag into a stock metric).

### Informational (not bugs — by design, worth knowing)
- **EV/EBITDA clamp:** `tool_d.py:344` nulls EV/EBITDA above `max_reasonable_ev_ebitda` (default 100×). At a very low stressed gold price a real company can exceed that and silently lose the component (renormalization then ranks it on 2 of 3). Deliberate sanity guard; just be aware it removes rather than caps. No test exercises this branch.
- **Net cash → negative leverage** ranks as "best" (`high_good=False`). Economically correct (net cash is good), but untested — worth one assertion.
- **Regime rolling window includes the current week** in its own 156-week quantile band. Standard for descriptive regime tagging and internally consistent; flagging as informational, not a bug.
- **`refresh` now fails loud on a Tool C/D error** (returns the tool's non-zero exit code even though A/B succeeded). Intended "one command, fail loud," but it *is* a behavior change to exit codes — fine, just noting.
- **No lint/type gate exists in the repo** (no `pyproject`/`mypy`/`ruff` config), so `compileall` + pytest are the only automated guards. Pre-existing condition, not introduced here.

---

## Verdict
This is a careful, well-structured build that correctly implements every locked decision and stays backward-compatible. **Two things to fix before this is relied upon:** **H1** (don't let the two presets silently change/drop tickers — denominator fix + parity test) and **H2** (the one-line `score_eligible` crash guard). Then strengthen the L2 test (**M1**) and add the four missing contract tests (**M2**); the dead columns (**L1**) are cleanup. After H1/H2 it's safe to merge; M1/M2 should land before the presets are trusted in anger.
