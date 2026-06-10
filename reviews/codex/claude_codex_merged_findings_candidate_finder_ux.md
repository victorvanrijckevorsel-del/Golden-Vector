# MERGED findings — Candidate Finder UX cleanup (Claude × Codex)

**Purpose:** the single fix-list for Codex to work from. Merges `claude_review_candidate_finder_ux_cleanup.md` (Claude, NEEDS CHANGES) and `codex_review_candidate_finder_ux_cleanup.md` (Codex, READY WITH MINOR CHANGES). Where the two reviews disagreed, the adjudication and its evidence are stated inline.

**Merged verdict: NEEDS CHANGES before commit** — adjudicated in Claude's favor because two findings Codex's review did not surface are proven by execution (F9 rendered HTML; F2 empirical rank-identity that changes the top-3). All required fixes are small: config copy, preset tuning, one alias map, test strengthening.

**Verification status note:** Claude ran the full suite first-hand (**896 passed in 12:20**) + ruff clean + focused 140 passed. Codex's pytest attempts timed out at 120s and the suite was NOT independently confirmed in its review — Codex must re-run the full suite after fixes with a longer timeout.

---

## 1. Comparison table

| # | Finding | Claude | Codex | Agreement / adjudication |
|---|---------|--------|-------|--------------------------|
| F9 | **Direction-baked descriptions contradict Bear's 7 flipped directions** — Bear's cards literally render "Lower debt burden. High values rank higher." (proven by executing the Bear page) | **HIGH** — blocker | — (missed; review says descriptions render cleanly) | **Claude — proven by execution.** The biggest finding in either review; fatal for an explainability-purpose change. |
| F2 | **`aisc` + `margin_pct` rank-identical → both presets double-count AISC** (~25–27% of each score; removing the dup changes the top-3 — proven empirically incl. ties/NaNs + 5,000-row randomized check) | **MEDIUM** — drop `margin_pct` from presets | Mentioned as "some correlation … acceptable because weights are visible and user-controlled" | **Claude — Codex's framing is factually wrong.** This is not correlation; it is bit-identical ordering (margin = 1 − AISC/G at a single per-run G). Visible weights don't help when no UI hint discloses the equivalence. |
| F1 / CX-2 | **`TOOL_D_FINDER_FIELDS` hand-list can drift from config** → a future Tool D criterion silently bypasses the non-spot guard | **MEDIUM** — drift-guard **test** (the new blanking test is a 3rd hardcoded copy, a mirror not a guard) | **MEDIUM** — derive guarded fields from config at runtime, or shared contract + config-driven regression | **Both found it.** Fix adjudicated to **Claude's test version**: a runtime derive-from-config intersect has **4 proven false positives** (`aisc_usd_per_oz`, `fcf_yield`, `market_cap_musd`, `reserve_life_years` — Tool B-owned columns the Tool D parquet also carries; naive blanking changes behavior in the tool_b-missing degraded path). The guard test must use `set(TOOL_D_OUTPUT_COLUMNS) − set(TOOL_B_OUTPUT_COLUMNS)`. |
| CX-1 | **Retired preset URLs silently become Bull** — `?preset=bearish_put` (a bearish bookmark!) now renders the Bull lens with no notice; the page swallows the raw id before the runner's existing "Unknown preset ignored" warning (`candidate_finder_data.py:235`) can fire; the current fallback test pins the silent behavior | — (missed; Claude checked for leftover code references to old ids, not inbound old URLs) | **MEDIUM** | **Codex — accepted, mechanism verified by Claude.** Fix adjudicated to Codex's **alias-map option** (`bearish_put→bear`, `bullish_call→bull`, `strong_corporate_finance→bull`): it *preserves the intent* of an old link instead of warning about it — a bearish bookmark stays bearish. |
| F4 | **No test proves WHICH preset is active/default** — both the "default bull" and "fallback" tests pass verbatim against Bear's HTML (proven by execution); byte-exact discriminating assertions provided | **LOW** | Partially adjacent (CX-1 notes the fallback test "pins silent behavior") but the does-not-discriminate defect itself not found | **Claude.** Folds naturally into CX-1's regression tests. |
| N1 / CX-3 | **"Lower 3.0x debt line is safer." hardcodes `debt_stress_leverage_danger_threshold: 3.0`** (`config/tool_d.yaml:3`) in prose — config changes, copy lies | **NIT** | **NIT** | **Both — same fix:** threshold-free copy. |
| S1 | **Bull barely expresses "benefits if gold rises"** — `up_beta` is 6.7% of the score, no `gold_beta_core`; effectively the old corporate-finance preset renamed | **MEDIUM (product)** | "Sensible first version" | **Claude's concern stands; final call = Emanuel** (product decision P1 below). |
| S2 | **Bear→puts flow lost IV-cheapness** — old `bearish_put` ranked option cost; Bear's fragile names carry the richest put IV; Options group renders collapsed | **MEDIUM (product)** | — | **Claude; final call = Emanuel** (P2 below). |
| S3 | Universe change kicks user out of preset mode (`custom=1` hidden input); clicking a preset resets Universe; backend already supports the combination | **LOW** | — | Claude. |
| S4 | `cost_curve` is a third rank-identical AISC proxy in the builder, undisclosed | **LOW** | — | Claude. |
| S5 | Debt-free companies score as *missing data* on the new stress-line criteria (safest names get a coverage penalty) | **LOW** | — | Claude. |
| S6 | All-or-nothing non-spot blanking now strips 2 of Bear's 8 criteria on a single bad row; warning names neither offenders nor reason | **LOW** | — | Claude. |
| S7 | Tool D criterion labels/copy still jargon ("Interest-cover gold", "stress line", "3.0x") — never says these are gold prices in USD/oz | **LOW** | — | Claude (combine with the F9 rewrite). |
| S8–S10, N2–N5 | Hardcoded "Bull or Bear" lead copy · `iv_skew` copy lacks a verdict (high skew = expensive puts) · Bear dropped the old `confidence` guard · `test_latest_data.py` indentation · lost YAML comment documenting Bear's intentional direction flips · `cli.py:780` "options side:" wording · spot-alias test doesn't assert the 4 new fields | **NITs** | — | Claude. |

**Where the reviews agreed and both are right (no action):** product framing (Bull/Bear + Universe) is the right shape; layering is clean (config → model → page, serve renders only); removing `fundamental_check_score` from the Finder is correct; the non-spot guard widening is conceptually right and covers all current fields.

---

## 2. Strengths comparison (honest accounting)

**Codex was stronger on:** the retired-URL user journey (CX-1) — a genuinely new finding Claude missed. Claude grepped for leftover *code references* to the old preset ids (found none) but never considered inbound old *URLs/bookmarks*. Good lens; mechanism verified correct first-hand.

**Claude was stronger on:** depth and proof. F9 was found by reasoning about direction overrides and **proven by rendering the Bear page** (7 of 8 cards self-contradictory — the single most user-visible defect in the change, absent from Codex's review). F2 was proven empirically where Codex hand-waved it as acceptable "correlation." F4 was proven by showing the named tests pass against the wrong preset's HTML. The 10 sweep findings (S1–S10) cover product coherence, modeling honesty, and copy. And the verification claim gap: Claude ran the full suite (896 green); Codex's timed out and was reported honestly but unconfirmed.

**Verdict adjudication:** Codex's READY WITH MINOR CHANGES cannot stand against a proven HIGH on a flagship preset of an explainability change → merged verdict **NEEDS CHANGES**.

---

## 3. THE FIX LIST (Codex: work top to bottom; review-verified file:line refs)

### Required before commit

**R1 (F9, HIGH) — Direction-neutral descriptions.** Rewrite the direction-baked descriptions in `config/candidate_finder.yaml` to neutrally state *what the metric measures*; the rendered "{High|Low} values rank higher." suffix and the Direction select carry the direction. Minimum = the 7 Bear-flipped criteria; do all direction-worded ones for consistency (custom screens can flip any criterion):
- `aisc`: "All-in cost to mine one ounce."
- `leverage`: "Debt load vs earnings (Net Debt / EBITDA)."
- `margin_pct`: "Profit cushion per ounce vs the gold price."
- `fcf_yield`: "Cash flow generated per dollar of share price."
- `reserve_life`: "Years of mine life remaining."
- `interest_cover_gold`: "Gold price where profit only just covers interest payments." *(also fixes S7 jargon)*
- `debt_stress_gold`: "Gold price where debt becomes heavy vs earnings." *(threshold-free → also fixes N1/CX-3)*
- `fcf_breakeven_gold`: "Gold price where cash flow hits zero."
- `cost_curve`: "Cost position vs peers (same ranking as AISC)." *(also fixes S4)*
- `ev_ebitda` / `forward_pe` / `iv_percentile`: neutral variants ("Price vs forward earnings power." etc.)
- `iv_skew`: "Extra downside fear priced into puts (makes puts cost more)." *(fixes S9)*
Tests: update the pinned copy assertion (`tests/test_candidate_finder_page.py:47`); **add a Bear-preset render regression** — render `query={"preset": ["bear"]}` and assert the leverage card hint is the new non-contradictory text AND `"Lower debt burden. High values rank higher."` is absent. Optional guard: config test that no description starts with a direction word (Lower/Higher/More/Less/Cheaper/Bigger/Stronger/Larger).

**R2 (F2, MEDIUM) — Remove the AISC double-count.** Delete the `margin_pct` entry from BOTH `bull` and `bear` presets (keep `aisc`, the industry-standard metric). If extra cost emphasis is wanted, use `aisc` at `weight: 2.0` with a YAML comment instead. Keep `margin_pct` available in the builder with the equivalence disclosed in its description (see R1 wording). Update the staged default-screen assertion expecting `criterion_margin_pct` (`tests/test_candidate_finder_page.py:43`).

**R3 (F1/CX-2, MEDIUM) — Drift-guard the blanking list (test, NOT runtime derivation).** Add a test asserting:
`set(TOOL_D_FINDER_FIELDS) == {c.source_field for c in config.criteria if c.source_field in set(TOOL_D_OUTPUT_COLUMNS) - set(TOOL_B_OUTPUT_COLUMNS)}`
(import `TOOL_D_OUTPUT_COLUMNS` from `golden_vector.model.tool_d`, `TOOL_B_OUTPUT_COLUMNS` from `golden_vector.screening.schema` — the subtraction encodes merge precedence; a naive config∩tool_d intersect has 4 confirmed false positives that change behavior in the tool_b-missing degraded path). Also replace the hardcoded 5-name tuple in `tests/test_candidate_finder_data.py:356-362` with iteration over the imported `TOOL_D_FINDER_FIELDS` (removes the third copy). Do NOT switch the runtime guard to config derivation in this PR.

**R4 (CX-1, MEDIUM) — Retired-preset alias map.** In the page layer (next to `_valid_preset_id`, `candidate_finder_page.py:489-496`): `_PRESET_ALIASES = {"bearish_put": "bear", "bullish_call": "bull", "strong_corporate_finance": "bull"}` applied before validation, so old bookmarks keep their intent (a bearish link stays bearish). Add one regression test per retired id asserting the right pill is `is-active`.

**R5 (F4, LOW) — Discriminating preset tests** (byte-exact strings verified against real rendered HTML):
- default test: `assert '<a class="candidate-preset is-active" href="/candidate-finder?preset=bull">Bull</a>' in html` and `assert '<a class="candidate-preset" href="/candidate-finder?preset=bear">Bear</a>' in html`
- fallback test: same is-active assertion **plus** `assert 'is-active" href="/candidate-finder?preset=bear"' not in html`
- optional content pin: `criterion_up_beta` present + `criterion_down_beta` absent on the default screen (up_beta is Bull-only, down_beta Bear-only — note R2/P1 may change the lists; pin after).

### Product calls — DECIDED by Emanuel (2026-06-10); Codex implements
**P1 (S1) — DECIDED: keep the math, fix the label.** Bull's criteria/weights stay EXACTLY as staged (`up_beta` remains 0.5; do NOT add `gold_beta_core`). Instead make the copy honest about what Bull is: a quality/value screen, not a rally-torque screen. Preferred implementation (consistent with this change's own config-copy philosophy): add an optional `description` field to the preset config model (same pattern as criterion descriptions) and render it under the preset bar — Bull: "Cheap, financially solid names to own if gold rises — ranks quality first, not rally torque." Bear: "Fragile names likely to fall hardest if gold falls." Minimum acceptable: reword the hardcoded lead sentence (`candidate_finder_page.py:56`) to the same effect. This resolution folds into C7 (the lead should no longer hardcode preset names either way).
**P2 (S2 + S10) — DECIDED: add BOTH back at half weight.** In `config/candidate_finder.yaml`, add to the `bear` preset: `iv_percentile` (direction `low_good`, `weight: 0.5` — favors names whose puts are still affordable) and `confidence` (direction `high_good`, `weight: 0.5` — restores the old guard against statistically weak down-beta estimates). Fragility criteria keep dominating the score by design. Expected side-effect (correct, don't "fix"): the Options criteria group will now auto-open under Bear since it has a selected member (`candidate_finder_page.py:252-253`). Ensure the iv_percentile/confidence descriptions read direction-neutral after R1.

### Recommended (small; same PR)
**C1 (N3):** Restore a YAML comment on the Bear preset documenting the *intentional* direction flips (the deleted `bearish_put` had one; Bear flips more and has none).
**C2 (S6):** Enrich the non-spot blanking warning with the offending tickers + reason (off-spot vs missing provenance) — keep all-or-nothing semantics for now.
**C3 (S5):** Append "missing = no material debt" to the two stress-line descriptions (folds into R1 wording).
**C4 (N4):** `cli.py:780` "options side:" → "universe:" for wording consistency.
**C5 (N2):** Fix the inconsistent dict indentation in `tests/test_latest_data.py:58-70`.
**C6 (N5):** In `test_candidate_finder_data_ignores_non_spot_mutable_tool_d_latest`, also assert one of the 4 new fields equals its spot-alias value.
**C7 (S8):** Make the lead sentence preset-agnostic or derive it from configured preset labels (`candidate_finder_page.py:56`).

### Allowed as a follow-up PR (bigger UI change)
**FU1 (S3):** Stop Universe↔preset fighting: carry `options_side` in preset pill hrefs and set `custom=1` only when criteria actually differ from the active preset. (Backend already supports the combination.)

### Done criteria
Ruff clean · focused Candidate Finder suite green · **full suite re-run to completion** (Codex's earlier runs timed out at 120s — use a longer timeout; Claude's baseline: 896 passed in ~12:20) · the new Bear render regression proves no contradictory card · Claude re-verifies first-hand before commit.
