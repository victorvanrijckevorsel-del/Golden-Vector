# Plan: Candidate Finder — multi-criteria weighted screener (v2)

**Author:** Claude Code (Opus 4.8)
**Branch:** `dev-vic`
**Date:** 2026-06-03
**Status:** for Codex re-review (v1 graded NEEDS CHANGES — `codex_review_claude_candidate_finder_plan.md`)
**Supersedes:** `claude_candidate_finder_plan.md` (v1). Design decisions unchanged (screener-builder UI; per-category top-N + blended weighted score; both lenses; equity = market cap; config-driven curated criteria). v2 fixes filter precision, freshness, missing-data determinism, percentile semantics, and config wiring.

## v2 changelog — every Codex v1 finding resolved
| Codex finding | Resolution |
|---|---|
| **R1 — options filter too coarse** (`tier != none` includes "thin"; side not considered) | §2d: the filter is now **side-aware "usable candidate"**, not `optionability_tier`. Inputs `has_usable_put_candidate` / `has_usable_call_candidate`, where "usable" = a side-specific candidate that **passes the quality gates** defined in the Option Trading clarity work (Good/Acceptable, not Poor/Rejected). The **preset lens picks the correct side** (bearish→puts, bullish→calls). |
| **R2 — freshness needs a gate/warning, not just a cache key** | §2g: add a **refresh-alignment check** (reuse the hedge report's context-alignment logic). If Tool A / Tool B / options / manual refresh runs disagree, the UI shows a strong **"mixed refreshes"** banner **above** the rankings and the blended score is flagged; optionally block. A cache key alone is not enough. |
| **R3 — missing-data renormalization can reward sparse rows** | §2c/§4: made **deterministic**. A row must meet `min_criteria_fraction` (default **0.67**) to be **rank-eligible**; low-coverage rows are **shown but always sorted BENEATH** eligible rows regardless of raw score. No more "optionally sink." |
| **R4 — percentile semantics underspecified** | §4: one explicit **`oriented_percentile` helper contract** — `rank(pct=True, ascending=<high_good>, method='average') × 100`, missing excluded from the pool, with a required **test matrix** (high-good, low-good, ties, all-missing, one-value, negatives). **Shared with Tool C/D** so View 1 and View 2 (and C/D) never disagree. |
| **R5 — config won't load unless the loader list is updated** | §3/§6: register `("candidate_finder","candidate_finder.yaml")` in `app/config.py::EXPECTED_CONFIG_FILES` and add the `candidate_finder` field to `AppConfig` — **in Batch 1 acceptance + tests.** |
| **R6 — "adding a criterion is a YAML edit" overpromises** | §2a: tightened to **"adding a criterion whose source field already exists in the joined frame is a YAML edit; new derived metrics or new sources (Tool C/D) need loader/scorer code + provenance."** |
| **OD-1 / OD-2 / OD-3** (Codex recs) | **OD-1:** top-N=10, `min_criteria_fraction=0.67`, low-coverage sorted beneath. **OD-2: defer** per-criterion threshold filters from v1 (options filter is the only filter). **OD-3: build now** on existing data; C/D plug in later. All adopted. |

---

## 0. The simplest thing that could work (v2)
> A "Candidate Finder" tab (+ CLI) that joins the latest Tool A / Tool B / options outputs + manual store by ticker, exposes a **config-driven** curated criteria list, and lets the user pick criteria + direction + top-N + weights (equal default). It shows **per-category top-N lists** and a **blended weighted ranking** where each criterion becomes an **oriented 0-100 percentile** averaged by weight — renormalized over present criteria, but **only rows meeting `min_criteria_fraction` are rank-eligible** (others sorted beneath). The options filter is **side-aware usable-candidate** (puts for a bearish lens, calls for a bullish lens), not raw optionability. A **refresh-alignment check** warns when sources come from different refreshes. The blended score is labeled **"fit to your criteria, not a return forecast."**

## 0.5. Dependency note (sequencing)
The side-aware **"usable candidate"** definition (R1) depends on the candidate **quality gates** being defined first (the Option Trading clarity work: delta-gap gate + Good/Acceptable/Poor/Rejected labels). So the cleanest order is: **(1) the clarity work lands the gate + `has_usable_put/call_candidate`, (2) the Candidate Finder consumes it.** If the Finder is built first, it must define a minimal usable-candidate check itself and the clarity work later points at the same definition — one source of truth either way.

---

## 1. Current state — criteria sources (verified 2026-06-03)
Unchanged from v1: Tool A (`down_beta_core`, `up_beta_core`, `structural_delta_core`, `confidence_score`, `downside_volatility_52w`, `score_eligible`), Tool B (`market_cap_musd`, `forward_revenue_musd`, `forward_ebitda_musd`, `forward_net_income_musd`, `forward_pe`, `ev_ebitda`, `fcf_yield`, `leverage`=Net Debt/EBITDA, `screening_verdict`, `best_upside_pct`), manual store (`aisc_usd_per_oz`, `net_debt_musd`, `production_oz`), options (`optionability_tier`, `iv_percentile_cross_sectional`, `iv_skew_60d`, **and the side-specific usable-candidate flags**), derived market-cap ratios (`debt_to_mktcap`, `ebitda_to_mktcap`, `revenue_to_mktcap`, `netincome_to_mktcap`).

---

## 2. Architecture

### 2a. Decisions locked
| Decision | Choice |
|---|---|
| Interaction | Screener-builder UI; criteria + direction + top-N + weights + preset lenses. |
| Scoring | Oriented-percentile blended score (§4), equal-weight default, user-adjustable. |
| **Options filter** | **Side-aware usable-candidate** (`has_usable_put_candidate` / `has_usable_call_candidate`), NOT `optionability_tier`. Preset lens picks the side. (R1) |
| **Freshness** | Refresh-alignment check → "mixed refreshes" warning / flag before rankings. (R2) |
| **Missing data** | Renormalize over present, but **require `min_criteria_fraction` (0.67) to be rank-eligible**; low-coverage shown but sorted beneath. (R3) |
| **Percentile** | One shared `oriented_percentile` helper with a tested contract. (R4) |
| Filters in v1 | Side-aware options filter only; **per-criterion thresholds deferred**. (OD-2) |
| Config | `candidate_finder.yaml` **registered in `EXPECTED_CONFIG_FILES`** + `AppConfig` field. (R5) |
| Registry claim | "YAML edit" only when the **source field already exists in the joined frame**; new metrics/sources need code. (R6) |
| Honesty | Blended score = "fit to your criteria," **not** a return forecast. |
| Equity | Market cap. |
| Sequencing | Build now on existing data; Tool C/D criteria added later. (OD-3) |

### 2b. Criteria registry (config-driven; v1 set)
Same curated list as v1 §2b (Sensitivity: down/up/core beta, downside vol, confidence; Fragility: AISC, Net-Debt/EBITDA, Debt/MktCap; Valuation: EBITDA/MktCap, Revenue/MktCap, EV/EBITDA, fwd P/E, FCF yield; Upside: best-upside%; Size: market cap; Options: IV percentile, IV skew). Plus the **options filter** is now its own thing (§2d), not a rank criterion. Each registry entry: `id, label, source_field, group, default_direction (high_good|low_good), unit, available_now`.

### 2c. Missing-data rule (deterministic — R3)
- Renormalize weights over the criteria a stock **has**.
- `criteria_fraction = present / selected`. A stock is **rank-eligible** only if `criteria_fraction ≥ min_criteria_fraction` (config, default **0.67**).
- **Rank-ineligible (low-coverage) rows are shown but always sorted beneath all eligible rows**, regardless of their raw blended score, with the `scored on K of N` flag. (Prevents a 1-of-5 stock topping the list.)

### 2d. Options filter (side-aware — R1)
- Inputs: `has_usable_put_candidate`, `has_usable_call_candidate` — **true only when a side-specific candidate passes the quality gates** (delta-gap within threshold; not Poor/Rejected) defined in the Option Trading clarity work. NOT `optionability_tier != none` ("thin" = listed-but-no-usable-candidate must NOT pass).
- The filter toggle is **lens-aware**: Bearish/put lens filters on `has_usable_put_candidate`; Bullish/call lens on `has_usable_call_candidate`; a neutral "any usable options" = either.
- Until the clarity gates land, the Finder uses a minimal usable check (a side candidate exists with `|delta_gap| ≤ threshold`); both later point at one shared definition.

### 2e. The two views (unchanged from v1)
View 1 = per-category top-N lists. View 2 = blended ranking with score, per-criterion percentiles, top-N tally, criteria-scored flag, eligible/low-coverage partition. Preset Bearish/Bullish lenses set sensible directions + the correct options side. Weight dials re-rank live. Screen spec in the URL (GET, no mutation, bookmarkable).

### 2f. Honesty / framing (unchanged)
Blended score labeled "fit to YOUR criteria/weights — not a return forecast." Low-coverage flag visible. Percentiles (not raw blended units) avoid false precision. **Mixed-refresh banner** (§2g) on top when sources disagree.

### 2g. Freshness / refresh-alignment (NEW — R2)
- On load, compare the refresh run ids across sources: Tool A `snapshot_refresh_run_id`, Tool B `snapshot_refresh_run_id`, options manifest `refresh_run_id`, manual-store hash. Reuse the hedge report's alignment logic (`report.py` context alignment).
- If they **disagree**, render a strong banner *above* the rankings: *"These rankings mix data from different refreshes (Tool A: …, options: …). Re-run `update-data` / the tools for a clean read."* — and tag the blended score as mixed. (Config can choose warn-only vs block; default warn-loudly.)
- The composite cache key (all source run ids) still prevents stale cache reuse — but the alignment check is what prevents a *clean-looking score over mismatched evidence*.

### 2h. Data layer & UI (as v1 §2g/§2h)
Loader joins latest outputs + computes derived market-cap ratios + the side-specific usable flags + the alignment status; caches on the composite key. Pure scoring engine (no I/O). New tab `/candidate-finder`; server-side math only; DataTables for display.

---

## 3. Module layout
As v1 §3, plus:
- `app/config.py` — **register** `candidate_finder.yaml` in `EXPECTED_CONFIG_FILES` (R5).
- `contracts/config_models.py` — add `CandidateFinderConfig` **and** the `candidate_finder` field on `AppConfig` (R5).
- `features/percentile_ranks.py` — the **shared** `oriented_percentile` helper (R4), reused by Tool C/D.
- `serve/candidate_finder_data.py` — also computes the **refresh-alignment status** (R2) and the **side-aware usable flags** (R1).

## 4. Math (v2 — explicit, R3/R4)
- **`oriented_percentile(series, *, high_good) -> Series`:** `series.rank(pct=True, ascending=high_good, method="average") * 100`. Missing values are excluded from the pool (NaN in, NaN out). This is the **single** convention; do NOT also use `100 − x` inversion (it changes endpoints/ties). Lowest non-missing value with `high_good=True` → `(1/n)·100`, not 0 — matching the existing IV-percentile convention (`features/options.py`).
- **Blended score:** `score(s) = Σ_{i∈present(s)} wᵢ·Pᵢ(s) / Σ_{i∈present(s)} wᵢ`, weights normalized over *selected* criteria, renormalized over *present*.
- **Rank-eligibility:** eligible iff `present(s)/selected ≥ 0.67`; ineligible rows sorted beneath all eligible rows (R3).
- **Required tests for the helper:** high-good, low-good, ties (average method), all-missing (→ all NaN), one-value (→ 100), negative values (e.g. negative betas), and a missing-data renormalization case.

## 5. Mock — as v1 §5, plus a top-of-page mixed-refresh banner when sources disagree, and the ranking split into an "Eligible" block above a "Low-coverage (scored on too few criteria)" block.

## 6. Order of operations (batched)
- **Batch 1 — config + scoring engine:** `candidate_finder.yaml` + `CandidateFinderConfig` + **register in `EXPECTED_CONFIG_FILES` + AppConfig field (acceptance + test — R5)**; the shared `oriented_percentile` helper + the full test matrix (R4); the pure scoring engine (blend, rank-eligibility, tally, deterministic missing-data — R3). → **Checkpoint A.**
- **Batch 2 — data/join layer + CLI:** join latest outputs + derived market-cap ratios + **side-aware usable flags (R1)** + **refresh-alignment status (R2)**; `candidate-finder` CLI (spec → ranked parquet) + tests (incl. a mixed-refresh case). → **Checkpoint B** (sample ranked output; mixed-refresh warning demoed).
- **Batch 3 — UI tab:** builder controls, View 1 + View 2 (eligible vs low-coverage split), preset lenses (correct options side), **lens-aware usable-options filter**, URL-spec, mixed-refresh banner, honesty labels. → **Checkpoint C** (completion report).

One commit per step; self-review per step; deeper review per checkpoint; no `git push`.

## 7. Acceptance criteria (v2 additions in bold)
- Tab + CLI produce View 1 + View 2 from structured data, server-side math only.
- **Options filter is side-aware usable-candidate (puts for bearish, calls for bullish), NOT raw `optionability_tier`; "thin"/no-usable-candidate names are excluded for that side.**
- Equal-weight default; weight changes re-rank; percentiles oriented per the **single** `oriented_percentile` contract (tested matrix).
- **Rows below `min_criteria_fraction` (0.67) are rank-ineligible and sorted beneath eligible rows, with a visible flag.**
- Derived market-cap ratios correct (market_cap > 0 guards; null not zero).
- **`candidate_finder.yaml` is registered in `EXPECTED_CONFIG_FILES`, validated into `AppConfig`, and hashed into provenance (tested).**
- **A mixed-refresh condition renders a loud warning above the rankings (tested).**
- Blended score labeled "fit-to-criteria, not a return forecast."
- Config-driven registry (adding a criterion whose field already exists = YAML edit); Tool C/D fields slot in when present.
- Full suite green; no live data in tests.

## 8. Out of scope (v1)
NLP/chat; saved named screens (URL-spec is shareable); **per-criterion threshold filters (deferred — OD-2)**; Tool C/D criteria population; backtesting.

## 9. Risks for the reviewer
1. The shared `oriented_percentile` must be the exact one Tool C/D use — confirm one implementation, not two.
2. The side-aware usable flag depends on the clarity-plan gates — confirm one shared "usable candidate" definition (§0.5), not a second drifting copy.
3. Refresh-alignment reuse of the hedge report logic — confirm it generalizes cleanly (it currently aligns Tool A/B/options for hedge readiness).
4. Rank-eligibility partition must be deterministic and visible — a low-coverage stock must never top the eligible list.
5. Provenance: cache key + alignment status both needed; confirm both are present.

## 10. Open decisions
**None** — OD-1 (top-N 10, min-fraction 0.67, sort-beneath), OD-2 (defer thresholds), OD-3 (build now) all resolved per Codex's recommendations. The one item worth the reviewer's nod: §2g default = **warn-loudly** (not block) on mixed refreshes.

## 11. Relationship to Tool C/D & the clarity plan
- **Tool C/D:** the Finder computes its own composite from raw metrics, so it doesn't need C/D; their ranks plug in later as extra criteria (config + loader for the new fields, per R6).
- **Option Trading clarity plan:** defines the candidate **quality gates** the Finder's side-aware options filter relies on (§0.5). One shared "usable candidate" definition across both.

## 12. Final self-review refinements (Claude, fresh-eyes pass — fold these into the build)
A critical re-read surfaced 8 tightenings. #1 and #2 are design-level (they refine §2c/§2d/§4); the rest are guards/clarity. All are now part of the plan.

1. **Percentile peer group = the POST-filter set (refines §4).** Compute every percentile over the candidate set that survives the hard options filter — *not* the whole 60-name universe. Rationale: "top 10 by AISC / down-beta" should mean "among the names you can actually trade for this thesis." View 1 and View 2 use the **same** post-filter pool so they agree. If no filter is on, the pool is the full eligible universe. *(Judgment call — chosen post-filter; trivial to flip to whole-universe if you prefer absolute context.)*

2. **"Usable candidate" is ONE shared primitive, built once (refines §0.5/§2d) — the most important refinement.** Extract a single `is_usable_candidate(candidate, config)` (delta-gap ≤ threshold + basic moneyness sanity) in the hedge layer. The Option Trading clarity UI, the candidate **quality labels**, AND the Finder's side-aware filter all call **the same** function. Do NOT let the Finder define its own "minimal" check that later diverges — that recreates the exact drift R1 warned about. This small primitive is a **prerequisite** for the Finder's options filter (and is needed by the clarity plan anyway) — build it first, once.

3. **Options side is its own control (refines §2d).** Expose **puts / calls / either** as an explicit toggle that the preset lens *initializes* but the user can change independently of the per-criterion directions (so a user can hand-build a screen without the filter silently fighting it).

4. **Input guards (add to acceptance + tests).** Empty criteria selection → friendly "pick at least one criterion"; all-zero or unset weights → fall back to equal; a single criterion → score = that one percentile. Never crash or divide by zero.

5. **Explain the score in plain English (UI).** Tooltip: *"Score = your weighted-average percentile across the criteria you chose (0–100). Higher = better fit to your screen. Not a return forecast."*

6. **Alignment is heterogeneous (refines §2g).** Compare run-ids for Tool A / Tool B / options; treat the **manual store** via its hash/as-of date separately. The mixed-refresh banner should name *which* source is out of step.

7. **CLI takes a screen-spec file (refines §3/§6).** Pass the spec (criteria, directions, weights, filter, N) as a small JSON/YAML file, not a pile of flags — reproducible, and mirrors the URL-spec shape.

8. **Score-ineligible Tool A values (refines §2c).** A name flagged `score_eligible=False` has unreliable betas; treat those beta criteria as **low-confidence/missing** for that stock (counts toward low-coverage) so a name can't ride a junk beta to the top. Surface the flag.

**Self-review verdict:** with #1–#8 folded in, the plan is internally coherent, honest, and the simplest thing that fully does the job. Two items remain genuine judgment calls (not gaps): §2g default = **warn-loudly vs block** on mixed refreshes (I chose warn-loudly), and refinement #1's peer group = **post-filter vs whole-universe** (I chose post-filter). Both are one-line config flips. Everything else is decided.
