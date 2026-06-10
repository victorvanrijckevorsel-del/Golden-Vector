# Claude review — Candidate Finder UX/product cleanup (Bull/Bear + Universe + Meaning)

**Reviewer:** Claude Code (Fable 5), first-hand — read the entire staged diff (12 files, +197/−117), read the surrounding model/serve/config code, ran ruff + the focused suite + the full suite myself, and adversarially verified every candidate finding with a 6-agent pass (including actually rendering the Bear page and quoting its real HTML).
**Scope:** the staged Candidate Finder cleanup — Bull/Bear presets, Universe relabel of `options_side`, the Meaning column (`description` in config), 4 new Tool D resilience criteria, `fundamental_check_score` criterion removed, `TOOL_D_FINDER_FIELDS` non-spot blanking widened.
**Review-only:** no code was changed.

**Verdict: NEEDS CHANGES (small, mostly config copy + preset tuning + test strengthening) — the architecture is right and clean, but one HIGH explainability defect ships on the Bear preset, and both presets silently double-count AISC.**

Verification I ran myself: `ruff check golden_vector tests` → clean · focused suite → **140 passed** · full suite → **896 passed in 12:20** (matches Codex's claim) · repo-wide grep → zero leftover `strong_corporate_finance`/`bearish_put`/`bullish_call` references.

---

## Verified first-hand (what's GOOD — all evidence-based)

- **The layering is exactly right (Q2).** `description` lives once in config (`config/candidate_finder.yaml`), is validated (`config_models.py:914` + the strip validator), threads `CandidateFinderCriterion → CriterionDefinition → ResolvedCriterion` via keyword-only construction (`model/candidate_finder.py:219-228`, `:434-442` — no positional construction anywhere), and renders in exactly two places, both HTML-escaped (`candidate_finder_page.py:309`, `:349`). No duplicated UI logic, no XSS.
- **Zero backend logic in serve (Q3).** The page diff is purely labels/copy/description rendering. The widened blanking guard lives in the data-assembly layer (`candidate_finder_data.py`), its pre-existing home. The criteria math stays in `model/candidate_finder.py`. Boundary intact.
- **Removing `fundamental_check_score` from the Finder is correct (Q4).** The column is still produced by Tool B for its real consumers (`screening/ranking.py`, `overview_tool_b.py` sort) — nothing orphaned. The finder frame no longer carries it because columns are config-driven (`_ensure_configured_source_fields`, `candidate_finder_data.py:451-457`), and the missing-sources test correctly switched its sentinel column to `aisc_usd_per_oz`. This also fits the standing "no opaque composite scores" rule.
- **The non-spot Tool D guard is complete TODAY (Q6).** Verified programmatically: `{configured source_fields} ∩ (TOOL_D_OUTPUT_COLUMNS − TOOL_B_OUTPUT_COLUMNS)` == the 5 members of `TOOL_D_FINDER_FIELDS` exactly. The new dedicated test (`test_candidate_finder_data.py:338-363`) genuinely exercises the widened path (deletes manifest + spot alias, mutates latest to non-spot, asserts all 5 NaN with real fixture values that would otherwise show).
- **The four new Tool D criteria are correctly oriented.** `low_good` verified right for all four: the three stress lines are "gold price where trouble starts" (lower = survives lower gold, `tool_d.py:313-326`), and `cost_curve_aisc_percentile` is `oriented_percentile(aisc, high_good=True)` so low percentile = low-cost producer (`tool_d.py:412-415`) — matching Tool D's own quality orientation.
- **Universe relabel is complete and consistent** in all three render sites (builder select `:185-190`, summary card `:163`, `_side_label` `:453-459`), "All stocks" correctly listed first; the real YAML is exercised by CI (tests copy the real config dir, `tests/helpers.py:23-28`).
- **Groups behave well:** `_render_builder_group` opens only groups containing selected criteria (`:252-253`) — so "Advanced Composites" renders collapsed under both presets, and Bear auto-opens Corporate Resilience. Exactly the "advanced stuff out of the way" intent.
- **Every description is consistent with its DEFAULT direction** (checked all 22) — the problem (F9) only appears when a preset *overrides* the direction.

---

## Findings

### F9 — HIGH: direction-baked descriptions contradict Bear's flipped directions — 7 of Bear's 8 explanation cards are self-contradictory on screen
The new descriptions are written for each criterion's **default** direction ("Lower debt burden.", "More cushion if gold falls.", "Lower all-in mining cost."…), but the Bear preset **deliberately flips direction on 7 of its 8 criteria** (fragility screen: `margin_pct→low_good`, `aisc→high_good`, `leverage→high_good`, `fcf_yield→low_good`, `reserve_life→low_good`, `interest_cover_gold→high_good`, `debt_stress_gold→high_good`). `_render_top_list_card` (`candidate_finder_page.py:345-349`) renders the static description followed by the **resolved** direction. **Verified by rendering the Bear page — these exact strings appear:**

> - "More cushion if gold falls. **Low** values rank higher."
> - "Lower all-in mining cost. **High** values rank higher."
> - "Lower debt burden. **High** values rank higher."
> - "More cash flow for price. **Low** values rank higher."
> - "More years of mine life. **Low** values rank higher."
> - "Lower stress line is safer. **High** values rank higher."
> - "Lower 3.0x debt line is safer. **High** values rank higher."

The builder has the same contradiction side-by-side (Direction select "High values fit" next to Meaning "Lower debt burden."). The **math is correct** — direction overrides are properly applied to ranking — only the explanations lie. But this change's entire purpose is explainability for a non-technical reader, Bear is one of two flagship presets, and a reader would conclude Bear surfaces low-debt names when it ranks high-debt names first. Any custom screen that flips a direction hits the same defect.

**Fix (config-only, no code):** rewrite descriptions direction-NEUTRAL — "what the metric measures," letting the rendered "{High|Low} values rank higher." carry the direction. E.g. `leverage`: "Debt load vs earnings (Net Debt / EBITDA)."; `aisc`: "All-in cost to mine one ounce."; `interest_cover_gold`: "Gold price where interest payments become stressed." Then update the one staged assertion that pins old copy (`test_candidate_finder_page.py:47`), and add a Bear-preset render regression asserting a non-contradictory card. Optional guard: a config test that no description starts with a direction word (Lower/Higher/More/Less/Cheaper…).

### F2 — MEDIUM: both presets double-count AISC — `aisc` and `margin_pct` are rank-identical
`margin_pct = (G − aisc)/G` with G a single per-run gold price (`layer1.py:44-53`) — a strict monotone transform of AISC with an **identical NA pattern** (margin is None exactly when aisc is None). Verified empirically: `oriented_percentile(margin, high_good)` equals `oriented_percentile(aisc, low_good)` bit-for-bit including ties and NaNs (plus a 5,000-row randomized check). **Both** Bull and Bear include both criteria with aligned direction pairs → each preset weights the single AISC signal **twice**: ~26.7% of Bull's score and 25% of Bear's is pure AISC (≈40% AISC-linked counting `fcf_yield`'s margin-driven numerator). End-to-end check confirms it's not a no-op: removing `margin_pct` changes the Bull top-3 (T03,T10,T04 → T03,T10,T01) and Bear top-3. The Meaning column compounds it by describing them as independent signals.

**Fix:** drop `margin_pct` from both presets, keep `aisc` (the industry-standard metric). If extra cost emphasis is intended, use `aisc` at `weight: 2.0` with a YAML comment. Keep both in the builder but disclose the equivalence in the margin description. One staged test assertion (`criterion_margin_pct` on the default screen) would need updating.

### F1 — MEDIUM: `TOOL_D_FINDER_FIELDS` is a hand-maintained second copy with no drift guard — and the new test is a third copy, not a guard
The canonical "which finder criteria come from the Tool D parquet" knowledge lives in config `source_field`s; `TOOL_D_FINDER_FIELDS` (`candidate_finder_data.py:41-49`) re-lists it by hand, and the new blanking test hardcodes the same 5 names again (`test_candidate_finder_data.py:356-362`). Complete today (verified) — but add a 6th Tool D criterion later and: `_ensure_configured_source_fields` surfaces the column, the non-spot guard does NOT blank it, and **non-spot scenario values get ranked as if spot, silently** — the exact degraded-data-must-be-excluded failure class — while the mirrored test keeps passing.

**Fix (prefer the guard over runtime derivation):** add a drift-guard test asserting `set(TOOL_D_FINDER_FIELDS) == {c.source_field for c in config.criteria if c.source_field in set(TOOL_D_OUTPUT_COLUMNS) − set(TOOL_B_OUTPUT_COLUMNS)}` (the Tool B subtraction encodes merge precedence — verified: a naive intersect would falsely blank 4 Tool B-owned columns the Tool D parquet also carries). And make the existing blanking test iterate the imported constant instead of its own copy.

### S1 — MEDIUM (product): the Bull preset barely expresses "benefits if gold rises"
Bull = 7 value/quality criteria at weight 1.0 + `up_beta` at **0.5** → gold-upside torque is **6.7%** of the score, with no `gold_beta_core` and no upside composite. It is effectively the old `strong_corporate_finance` preset renamed. Bear is asymmetric (down_beta at full 1.0 = 12.5%). A user clicking "Bull" gets cheap, low-debt majors — often the *lowest*-torque names in a gold rally — under a label that promises the opposite.
**Fix:** raise `up_beta` to 1.0 (symmetry with Bear) and consider adding `gold_beta_core`; or soften the lead copy to match the math ("quality names to own if gold rises").

### S2 — MEDIUM (product): the Bear→puts flow lost IV-cheapness exactly where puts are most expensive
The deleted `bearish_put` preset paired its put filter with `iv_percentile low_good` (cheap options). New Bear has no Options criterion, and Bear's top names (high down-beta, fragile balance sheets) are precisely where the market prices the richest put IV — so the advertised two-step (Bear + Universe="Only stocks with puts") systematically points at the most expensive puts, and the Options criteria group renders collapsed (nothing selected). **Fix:** add `iv_percentile` (low_good, weight ~0.5) to Bear, or render a one-line tip when Universe is puts/calls.

### F4 — LOW (test fidelity): no test proves WHICH preset is active or default — proven by rendering Bear
`test_..._renders_default_bull_screen` and `test_..._invalid_preset_falls_back_to_default` **pass verbatim against HTML rendered with `preset=bear`** (verified by execution): `>Bull</a>`/`>Bear</a>` match the always-rendered link bar, `candidate-preset is-active` only proves *some* preset is active, and `criterion_margin_pct`/"Use Margin %"/"More cushion…" appear under both presets (margin is in both; builder rows render for every criterion regardless of selection). A regression flipping the default to Bear would pass CI.
**Fix (byte-exact strings verified against real output):** assert `<a class="candidate-preset is-active" href="/candidate-finder?preset=bull">Bull</a>` in both tests, plus `is-active" href="/candidate-finder?preset=bear"` **not** in html for the fallback test; optionally pin screen content with the discriminating criteria (`criterion_up_beta` present, `criterion_down_beta` absent — up_beta is Bull-only, down_beta Bear-only).

### S3 — LOW (UX): the two advertised decisions fight each other in the UI
The lead promises "choose Bull or Bear, then choose Universe" — but the Universe select sits inside the builder form which hardcodes `custom=1` (`candidate_finder_page.py:214`), so changing Universe un-highlights the preset and declares "Custom criteria are active"; and preset pills link to `?preset=<id>` only (`:126`), so picking Universe first then clicking a preset **resets Universe**. The backend already supports the combination (`_screen_spec_from_query` reads both independently; the CLI test uses `preset: bear / options_side: puts`) — the UI just never generates that URL. **Fix:** carry `options_side` in preset pill hrefs and only set `custom=1` when criteria actually differ from the active preset.

### S4 — LOW: `cost_curve` is a third rank-identical AISC proxy in the builder
`cost_curve_aisc_percentile` = pure monotone AISC transform (`tool_d.py:412-415`; empirically identical percentiles). Not in any preset, but the builder now offers `aisc` + `margin_pct` + `cost_curve` with no hint they are the same ordering — a user checking all three silently triple-weights AISC. **Fix:** disclose in the Meaning text ("same ranking as AISC") and add a YAML comment so future presets never combine them.

### S5 — LOW (modeling honesty): debt-free companies score as *missing data* on the new stress-line criteria
`_debt_stress_gold` returns None when net debt ≤ 0; `interest_cover_gold` is None when interest expense ≤ 0 (`tool_d.py:594-627`). Under `low_good`, the structurally **safest** names get no percentile credit and a coverage penalty (`candidate_finder.py:365-367`), while an indebted miner with a low stress line ranks best. Acceptable v1 semantics, but say it: add "missing = no material debt" to the descriptions, or (a Tool D modeling decision, separate change) emit a 0 stress line for net-cash names.

### S6 — LOW: all-or-nothing blanking now strips 2 of Bear's 8 criteria on a single bad row, with an unhelpful warning
One row with off-spot or NaN provenance blanks all 5 fields for **every** ticker (`is_spot.all()`, `candidate_finder_data.py:827-839`). Pre-existing pattern (was quality-rank-only), but the widening raises the blast radius onto Bear's criteria, and the warning neither names the offending tickers nor distinguishes "off-spot" from "missing provenance." **Fix (either):** per-row masking, or keep all-or-nothing and enrich the warning with the offenders + reason.

### S7 — LOW (copy): the new Tool D labels/descriptions are still jargon
"Interest-cover gold", "Debt-stress gold", "Lower stress line is safer", "Lower 3.0x debt line is safer" assume the reader knows Tool D's lines — the builder never says these are **gold prices in USD/oz**. Tool D's own page needs tooltips to explain them (`overview_tool_d.py:221`, `:291`). **Fix:** plain-English gold-price framing, e.g. "Gold price where profit only just covers interest payments." (Combines naturally with the F9 rewrite.)

### Nits
- **N1:** "Lower **3.0x** debt line is safer." hardcodes `debt_stress_leverage_danger_threshold: 3.0` (`config/tool_d.yaml:3`) in prose — change the config and the description silently lies (the single-source-threshold rule applied to copy). Drop the number or phrase it as "the configured debt line."
- **N2:** `test_latest_data.py` dict re-indentation is inconsistent (entries at mixed indent levels) — valid Python, sloppy to read; tidy it.
- **N3:** the old `bearish_put` preset carried a YAML comment documenting its **intentional** fragility direction-flips; Bear has *more* flips and no comment. Restore the comment so a future reader doesn't "fix" `aisc: high_good`.
- **N4:** one leftover "options side:" string in a CLI message (`cli.py:780`) — inconsistent with the new "Universe" language.
- **N5:** `test_candidate_finder_data_ignores_non_spot_mutable_tool_d_latest` asserts only `tool_d_quality_rank` comes from the spot alias — could also assert one of the 4 new fields equals its spot-alias value.
- **S8:** the lead sentence hardcodes "Bull or Bear" and `_DEFAULT_PRESET_ID="bull"` in serve while presets are config-driven; `_valid_preset_id` falls back gracefully (`:489-496`) so this is cosmetic — derive the lead from preset labels or use preset-agnostic wording.
- **S9:** `iv_skew` description ("Higher put fear priced in.") states a fact without a verdict — and high skew literally means puts cost extra, a tension for a put buyer; make the copy carry the trade-off.
- **S10:** Bear dropped the `confidence` guard the old `bearish_put` deliberately paired with `down_beta` — statistically weak beta estimates now rank at full strength. Add `confidence` (~0.5) or note the decision.

---

## The 7 questions, answered directly

1. **Product framing right?** The Bull/Bear + Universe decomposition is the right shape and matches Emanuel's ask — qualified by S1 (Bull doesn't yet express "bull"), S2 (Bear+puts blind to option cost), and S3 (the two controls fight in the UI).
2. **Layering clean?** Yes — config-validated description, threaded through keyword-only dataclasses, rendered escaped in two places, zero duplicated UI logic.
3. **Backend logic in serve?** None added. Page = labels/copy only; the guard lives in the data layer; math stays in the model.
4. **`fundamental_check_score` removal correct?** Yes — finder orphans nothing, Tool B consumers untouched, sentinel test switched appropriately, and it serves the "no opaque composites" rule.
5. **Bull/Bear sensible, not double-counting?** Mostly sensible — except both presets double-count AISC (F2, proven), Bull under-weights its own thesis (S1), and Bear lost IV-cheapness (S2) and the confidence guard (S10).
6. **Non-spot guard correct for all Tool D fields?** Complete and tested **today** (verified programmatically) — but it's an unguarded hand-list that will silently drift (F1), and the all-or-nothing semantics now have a wider blast radius (S6).
7. **Weak tests?** Yes: neither the default-bull nor the fallback test discriminates the active preset — both pass against Bear's HTML (F4, proven by execution); the blanking test mirrors the hand-list instead of guarding it (part of F1); plus N5.

## Bottom line
Architecturally this is exactly what was asked: descriptions in config, serve renders only, internal field names gone, the options filter reframed as a Universe decision, the opaque composite demoted, and the non-spot guard correctly widened with a real test — 896 green, verified first-hand. What blocks commit is small but real: **F9** (Bear's explanations contradict its own ranking — fatal for an explainability change, config-copy fix), **F2** (drop `margin_pct` from both presets — AISC is counted twice, provably changes the top-3), **F1** (add the drift-guard test so the blanking list can't silently rot), and **F4** (make the preset tests actually discriminate). S1/S2 are product calls for Emanuel: raise `up_beta` to 1.0 (and/or add `gold_beta_core`) so Bull means bull, and give Bear back an IV-cheapness term for the puts flow. Everything else is copy polish and nits. With F9/F2/F1/F4 fixed, this is a clear approve.
