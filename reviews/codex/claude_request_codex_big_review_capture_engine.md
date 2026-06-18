# Codex — big independent review of the Capture & Behaviour engine

**You are Codex, an independent senior reviewer.** Claude built this engine across 5 phases and it
has already passed 5 internal reviews. Your job is the **adversarial last look**: find what those
reviews missed, confirm-or-refute the fixes they claim, and pressure-test the math, the data
integrity, and the honesty of every number shown to the user. Assume there is at least one real
bug left. Be exhaustive and first-hand.

---

## 0. How to work (use agents; be thorough)

1. **Fan out, don't single-thread.** Spawn one agent per review dimension (§4) in parallel, each
   reading the real code file-by-file. Then run a **second adversarial pass**: for every candidate
   finding, spawn 2–3 independent skeptic agents prompted to *refute* it (default to "not a bug" if
   uncertain). Keep a finding only if it survives — a majority-refute kills it. This two-stage
   find→verify loop is mandatory; do not ship unverified findings.
2. **First-hand, every claim cited.** Read the current tree, not the review docs. Every finding must
   carry `file:line` and a quoted snippet. Trust no prior review (Claude's or your own earlier one)
   over what the code says *now* — the holistic fixes (commit `69ed781`) are in the tree; verify they
   actually do what their doc claims.
3. **Show ALL findings**, including nits — never truncate or "+N more". Merge duplicates into one row
   with all sightings.
4. **Don't rediscover settled issues** (§3) and **don't re-open locked product decisions** (§2).
   If you believe a locked decision is wrong, say so in a separate "product challenges" section with
   evidence — don't spend the correctness review on it.
5. **Match rigor to risk.** The engine is exploratory/descriptive (nothing ranks live yet), so a
   silent-stale or a wrong-label bug is HIGH; a cosmetic copy nit is a NIT. Use the severity rubric in §5.

---

## 1. What the engine is + its code surface (verified inventory)

A **symmetric (gold-down AND gold-up) "Capture & Behaviour" layer** on the Lab's `/lab/dial/<ticker>`
drill-down. It answers, per miner: how much of gold's fall/rise it captures (capture ratios +
convexity), which of 4 archetypes it is (HEDGE / TORQUE / CONVEX / DEAD_WEIGHT), how it ranks vs
peers, and whether its behaviour is *changing over time* (event-time recent-vs-older trend). It is
**descriptive, survivor-only, not predictive** (see §2).

It is built **on top of** the Conditional Dial "episode spine" (`conditional_dial.py`): one row per
`ticker × week × horizon × benchmark`, with forward returns, gold buckets, alpha, beat flags, and a
`is_nonoverlap_anchor` flag for independent episodes.

**Core files (read all of these):**

| File | ~Lines | Role |
|------|--------|------|
| `golden_vector/lab/statistics.py` | 286 | Shared pure-numpy primitives: `wilson_interval`, `eb_shrink`, `pooled_prior`, `decay_weights`, `decay_effective_n` (Kish ESS), `mann_kendall`, `theil_sen`, `benjamini_hochberg`, `peer_percentile`, `two_proportion_p`, `mde_proportion_pp`; re-exports `weighted_median`. |
| `golden_vector/common/stats.py` | 43 | `weighted_median(values, weights)` — the one shared copy (model + lab). |
| `golden_vector/lab/behavior_engine.py` | 1233 | The engine. `compute_capture_table`, `capture_distribution`, `compute_peer_points`, `compute_peer_snapshot`, `compute_trend_table`, `build_capture`, `build_and_save` (compute→persist), `behavior_config_hash`, `_warn_cutoff_drift`, `main()`. |
| `golden_vector/lab/conditional_dial.py` | 1148 | The spine it depends on. Relevant: `DIAL_SCHEMA_VERSION=4`, `DIAL_HORIZONS_WEEKS=[4,8,13,26]`, `DIAL_BENCHMARKS=[GDX,GDXJ]`, `DEFAULT_BUCKETS`/`DOWN_BUCKETS`/`UP_BUCKETS`, `EPISODE_COLUMNS`, `dial_meta.json`, `dial_config_hash`. |
| `golden_vector/contracts/config_models.py` (≈694–772) | — | `CaptureBehaviorConfig` (+ validators `finite_numbers`, `fraction_strictly_inside_unit`). Defaults: `hedge_down_capture_max=1.69`, `torque_up_capture_min=2.20`, `default_capture_horizon=13`, `default_trend_horizon=8`, `min_direction_effective_n=6`, `min_anchor_episodes=6`, `trend_delta_threshold=0.20`, `q_fdr=0.10`, `eb_prior_strength=10`, `recent_anchor_fraction=0.5`, `min_anchors=8`, `min_peer_count=20`, etc. |
| `config/lab_behavior_trend.yaml` | 37 | The values, folded into `behavior_config_hash` (separate from the spine's `dial_config_hash`). |
| `golden_vector/serve/lab_curve_data.py` | 714 | Read-only loader. `_load_behaviour`, `_behavior_is_current`, `_row_for_keys`, `_read_meta`, `load_ticker_curve`, `LabCurveData`. **No arithmetic allowed here.** |
| `golden_vector/serve/lab_curve_page.py` | 922 | Render only. `_render_behaviour` (3 cards), `_ARCHETYPE_BLURB`. **No arithmetic allowed here.** |
| `golden_vector/common/parquet.py` (≈270) | — | `write_run_stamped_set(...)` — all-or-nothing publish (run-stamped files first, then latest aliases, meta last). |

**Tests (102 functions):** `tests/test_behavior_engine.py` (26), `test_behavior_peer.py` (15),
`test_behavior_trend.py` (21), `test_lab_statistics.py` (15), `test_lab_behaviour_panel.py` (12),
`test_lab_page.py` (13, includes a static guardrail that forbids compute in serve).

**Artifacts** (run-stamped + `*_latest` alias): `dial_capture`, `dial_peer_points`, `dial_peer`,
`dial_behavior_trend`, and `behavior_meta.json` (written last; carries `behavior_config_hash`,
`spine_schema_version`, `source_spine`, `capture_distribution_default_horizon`, counts, timings).
**Build entry point:** `python -m golden_vector.lab.behavior_engine`.

---

## 2. Locked decisions & deferred scope — do NOT re-open these as bugs

**Locked product decisions** (settled with the founder; critique only in a separate section, with evidence):
- **Capture is measured vs GOLD only** (not vs GDX/GDXJ). Peer ranking is the benchmark-independent cross-section.
- **Offense default = CONVEX** (the "torque" archetype the founder cares about).
- **13-week capture levels / 8-week trend** — capture/archetype pinned to `default_capture_horizon=13`, behaviour-change pinned to `default_trend_horizon=8`, both decoupled from the page look-ahead.
- Archetype cutoffs are **relative-to-universe terciles** (grounded on cross-sectional p33/p67), not absolute.

**Deferred scope** (the engine is allowed to NOT have these yet — do not file them as missing features):
- **Phase 5 walk-forward backtest** — nothing here ranks live or claims predictive power until this exists.
- Capture-trend (the trend layer covers beat-rate + alpha, not capture levels over time — by design).
- Dead-miner / delisting registry (survivor-only is a *known, disclosed* caveat, not a bug to fix here).

**The honesty frame:** every number must read as **descriptive of the past, survivor-only, not a
forecast**. A finding that the engine *implies prediction* anywhere is in-scope and serious.

---

## 3. Already found & FIXED — confirm-or-refute, do not rediscover

Five prior reviews (Codex Phases 0–3 + Claude per-phase + a 5-dimension/23-agent holistic pass)
locked down the items below. **Your job on these is to verify the fix is real and complete** (or
prove it isn't) — not to re-report the original symptom. Records:
`reviews/codex/codex_review_capture_behavior_engine_phases_0_3.md`,
`claude_codex_review_resolutions_phases_0_3.md`, `claude_phase{1,2,3}_*review*.md`,
`claude_phase4_ui_review.md`, and `claude_holistic_review_resolutions.md`.

The 6 most recent fixes (commit `69ed781`) to confirm-or-refute:
1. **Cross-artifact staleness.** `_load_behaviour` now reads live `dial_meta.json` and forces
   `behavior_status="STALE"` unless `behavior_meta.source_spine.episodes_artifact ==
   dial_meta.run_stamped_artifacts.episodes`. **Probe:** is the comparison correct on every path
   (data refresh, config change, identical re-run)? Does it fail *open* anywhere (both pointers
   present but one malformed)? Is the fixture-skip (missing pointer) exploitable in production?
2. **Trend pinned to 8w** (`default_trend_horizon`), decoupled from page horizon; labelled.
   **Probe:** can a horizon mismatch still leak the 13w row into the 8w card?
3. **Cutoffs re-grounded** 1.61/2.17 → 1.69/2.20 + `_warn_cutoff_drift` at build (tolerance 0.15).
   **Probe:** does the warning fire on every run and read the right quantiles? Is 0.15 too loose?
4. **Null archetype NaN→None** normalization in `_row_for_keys` + `_present()` render guard (a null
   archetype must never render as a bold "nan"). **Probe:** every behaviour field, every status.
5. **Label-basis hints** (the bold trend label is decided on peer-adjusted/shrunk rates).
6. **`decay_*` columns** marked descriptive/reserved (not label-driving).

---

## 4. Review dimensions + concrete probes

Run each as its own agent (or cluster). The line numbers below are leads surfaced by an internal
mapping pass — **verify them against the current tree**, they may have shifted.

### A. Statistical & financial correctness (the core)
- **Effective-N deflation for overlapping labels.** Every `effective_n`/`decay_effective_n` call on
  *overlapping weekly* statistics must pass `label_horizon_weeks=horizon` (≈ lines 232, 585, 915).
  If any defaults to `1`, overlapping labels are NOT deflated → variance understated → p-values too
  hot. **Conversely**, *anchor* statistics (independent episodes) must NOT be deflated again
  (`label_horizon_weeks=1` is correct for them, ≈ lines 939/948/954). Hunt for both the missing
  deflation and the double deflation.
- **Capture ratio denominators.** `_capture_side` (≈244): is `gold_mean == 0` *and* non-finite
  guarded before dividing? Are stock/gold coerced and NaN-paired-dropped consistently (≈225–228)?
- **trend_delta prior contamination.** `trend_delta = rec_shrunk - old_shrunk` (≈928) shrinks each
  window toward its *own* window prior. The docstring now admits these don't perfectly cancel.
  **Verify** the residual prior shift cannot push a cell over `trend_delta_threshold=0.20` *and*
  past the raw-anchor MK sign gate + raw-count FDR simultaneously (the claim is the raw gates guard
  it — prove or break that).
- **Two-proportion z + MDE at tiny n.** `two_proportion_p` uses a normal approximation; many cells
  have n≈4–8. Is the abstention (effective-N floors) tight enough that the normal-approx regime is
  never trusted for a *fired* label? `mde_proportion_pp` hard-codes p=0.5 (conservative) — confirm.
- **Mann-Kendall / Theil-Sen.** MK assumes chronologically sorted input (≈155 via `np.subtract.outer`);
  confirm the caller sorts (≈791) and no other caller feeds unsorted anchors. Alpha trend requires
  MK *and* Theil-Sen sign agreement (≈904) — verify the AND is real.
- **FDR scope.** BH-FDR is per `(benchmark, horizon, gold_bucket)` family (`TREND_FDR_SCOPE`), q=0.10.
  Is scenario-local (not global) FDR defensible here, and is the family construction leak-free
  (no cell counted in two families, no singleton family that auto-passes)?
- **Archetype grounding & cross-horizon.** `capture_distribution` must ground p33/p67 on
  `capture_status=="OK"` rows only (≈1151). Archetype is emitted only at `default_capture_horizon`
  (≈381) — confirm no label leaks at other horizons. Check the anchor cross-check confidence logic
  (`confirmed` / `unconfirmed_disagrees` / `unconfirmed_thin_anchor`, ≈381–394).
- **Wilson interval** is defined but appears unused by capture/trend — confirm intentional, not a
  dropped gate.

### B. Data integrity & provenance (the riskiest boundary)
- **Spine→Behaviour handoff** (≈1042–1087, esp. 1069–1076): the build resolves the episode file via
  the dial manifest pointer but **falls back to the `*_latest` alias** if the pointer is missing.
  Can a stale/empty `*_latest` alias silently poison a behaviour build? Should it fail loud instead?
- **Two independent build entry points** (`conditional_dial` then `behavior_engine`) with **no
  orchestrator** forcing the pair. Map every way the two can desync and whether serve catches each
  (the staleness fix in §3.1 is the only guard — is it sufficient?).
- **All-or-nothing publish** (`write_run_stamped_set`): prove a crash mid-publish leaves the last
  good state intact (run-stamped first, latest aliases, meta last). Any partial-failure window?
- **The two hashes.** `dial_config_hash` (spine) vs `behavior_config_hash` (behaviour) — enumerate
  exactly what each folds in and **what NEITHER covers** (episode *data*), and confirm the
  `source_spine` cross-check closes that gap on every refresh path.
- **Fail-loud vs degrade-per-item.** Required inputs must fail loud; one bad ticker must mark that
  ticker and continue (never `except: return empty`). Find any required-data path that degrades silently.

### C. Architecture / one-copy / serve-renders
- **No arithmetic in serve.** `lab_curve_data.py` / `lab_curve_page.py` must only select + format.
  Hunt for any ratio, coalesce/fallback resolution, rank-basis decision, or unit conversion that
  belongs in the model layer. (There is a static guardrail test — confirm it actually covers the new
  behaviour entry points and can't be bypassed.)
- **One copy of everything.** Did any primitive get re-implemented instead of imported from
  `statistics.py` / `common/stats.py`? Any forked capture/peer/trend logic between build and serve?
- **Every threshold in config.** Any hardcoded constant that duplicates a `CaptureBehaviorConfig`
  value (twins drift)?

### D. Tests prove behaviour (not pass by accident)
- Do exclusion/abstention tests use a *healthy control* alongside the degraded subject? Do
  determinism tests include deliberate ties + NaN? Are user-facing strings asserted at render level?
- Is there a test that would actually **fail** if effective-N deflation were dropped, or if the
  staleness cross-check were removed? (Mutation-test the guards in your head.)
- The cutoff-grounding: is there anything that catches future drift beyond the soft build warning?

### E. Predictive-models rigor (small-universe honesty)
- ~60 names, weekly, overlapping labels, survivor-only. Confirm **nothing** here implies a tradeable
  edge or a forecast. Any significance claim must clear a high bar (t≈3, not 2) — but note this layer
  is descriptive, so the real check is that it never *presents* itself as predictive.
- Point-in-time: confirm no future data leaks into any cell (peer ranks, priors, windows all use only
  data available as-of the episode week).

### F. Product honesty / UX of the panel
- Does every displayed number carry its basis (horizon, direction, benchmark-free vs peer, effective-N)?
- Do the abstain/thin/stale/corrupt states each render an honest, distinct message (no confident
  number on thin evidence; no "nan"; no stale-as-current)?

---

## 5. Severity rubric & deliverable

**Severity:** HIGH = wrong number/label shown as confident, silent stale/leak, or a data-integrity
break. MEDIUM = correctness gap gated by luck/abstention, or a real honesty/label-basis issue.
LOW = narrow-condition or cosmetic-but-real. NIT = style/doc/dead-code.

**Deliver one markdown file** at `reviews/codex/codex_review_capture_engine_big.md` containing:
1. A findings table: `# | Severity | Dimension | File:line | Finding | Why it's real (cite code) |
   Verifier verdict (survived N skeptics) | Suggested fix`.
2. For each "already-fixed" item in §3: **CONFIRMED / INCOMPLETE / REGRESSED** with evidence.
3. A short "product challenges" section (only if you think a locked decision is genuinely wrong — evidence required).
4. A prioritized fix list (what to fix before this engine is built on further).

**Do not change code** while reviewing (the only exception is if something literally crashes the
app — then note it loudly). After the review is written, fixes happen as a separate, deliberate pass.

The repo's senior-engineering canon (`CLAUDE.md`, `soul.md`, `ARCHITECTURE_FOUNDATIONS.md`) and the
`.claude/skills/predictive-models/SKILL.md` rules are the standard to hold this against. Be the
review that finds the bug the other five missed.
