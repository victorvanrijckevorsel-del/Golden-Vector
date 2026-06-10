# Plan v2 — Gold price dial (spot by default) + dual-source fundamentals

**Author:** Claude Code (Opus 4.8). **Supersedes** `claude_gold_dial_and_fundamentals_plan.md` (v1).
**Status:** v2.1 — incorporates Codex's SECOND-pass review (`codex_review_claude_gold_dial_and_fundamentals_plan_v2_second_pass.md`, READY WITH CHANGES: 2 HIGH / 4 MEDIUM / 1 NIT — all seven adopted after first-hand verification, three with stronger mechanisms than Codex proposed; see §0.6). **BUILD-READY.** Build order: Tier 1 (PR1→PR2) → Tier 2 (PR3, after the staged Finder UX cleanup lands) → Tier 3 (PR4→PR5→PR6).
**How this was verified:** every file:line below was read first-hand against the current repo (HEAD `39074f1`). Where Codex's citations were stale or off-by-a-row, the corrected line is used and the slip is noted. Where the verification found a gap **neither v1 nor Codex caught**, it is flagged `[NEW]`.

---

## TL;DR (plain English)

The point of the feature is unchanged: open the tool and every gold-dependent number is at **today's gold price** (dated), with **one dial** to explore any price, and fundamentals that can be **auto-pulled from Yahoo while keeping your own corrected number beside the official one**.

Codex was right that v1 under-specified the *data plumbing*. The two big changes in v2:

1. **Ship it in three tiers, smallest-correct-thing first.** Tier 1 (two small PRs) fixes the entire "EV/EBITDA 3.87 looked wrong" confusion by itself — default to dated spot + one gold dial. Everything else (the Candidate-Finder dial, the auto-pull, the Official/Our-view comparison) is a separate, later data project that does **not** block the fix.
2. **A much simpler store design.** Your hand-typed numbers already *are* "our view." So we just **add one new read-only data file** for the official Yahoo numbers (a standard model artifact, tracked like every other output) and compare against what's already there — your store is never touched at all. Undo = delete one file.

**All product decisions are now fully resolved (Emanuel, 2026-06-10 — see §0/§9):** the comparison ships as an always-visible **"Market | Ours"** side-by-side pair plus a **"Rank by: [Our view | Official]"** control and a **"differences only"** filter (ordered by largest disagreement first); the forward-vs-trailing rank toggle and the @normalized column are **cut**; `tax_rate` stays manual; the Finder dial (Tier 2) is **IN scope — built right after the Tool B dial (PR1 → PR2 → PR3), before the translator** (Emanuel: the Finder is his most-used tool). Nothing is open.

---

## 0. Locked product decisions (UNCHANGED — not re-litigated) + how v2 sequences each

| # | Locked decision | v2 treatment |
|---|---|---|
| 0.1 | **Saved run = spot.** Overnight pipeline persists gold-dependent metrics at today's spot; other prices computed live, never persisted. | **Tier 1, PR1.** Becomes the canonical run. (Tool D already works this way — we copy it.) |
| 0.2 | ~~Ranking = forward-vs-trailing toggle~~ → **REVISED (Emanuel, 2026-06-10): the forward-vs-trailing rank toggle is CUT.** | One rank rule everywhere: **forward metrics at the dialed gold price, on the selected data layer (§0.4)**. The trailing-actual figure still renders as a clearly-labeled column in Tier 3, but is **never a sort basis** — a trailing rank inherits the trailing-period choice (latest annual vs TTM, §5h.6; Emanuel: "it could change everything" — exactly), and composed incoherently with a moving dial. Cutting it removes that confusion class by construction. |
| 0.3 | **One dial** (unchanged). ~~"@spot \| @normalized" companion pair~~ → **REVISED (Emanuel, 2026-06-10): the @normalized companion column is CUT.** | The dial + presets already reach any gold price, so the dedicated normalized column added nothing Emanuel wanted. `gold_price_basis` stays an extensible string, so `normalized_3y_avg` can return later with zero schema change if ever wanted. No 3-yr-average computation, no config knob. |
| 0.4 | **Keep BOTH numbers, never overwrite; compare** (storage unchanged) — **display/sort form REVISED (Emanuel, 2026-06-10): side-by-side, not a display toggle.** | Storage: by construction via the additive store (§5b/§5c). Display: an **always-visible "Market \| Ours" pair** on the key ratios, rendered only where the user's figure differs from Yahoo's (adopted §9-A). Sort: a **"Rank by: [Our view \| Official]"** control — the layer toggle survives as the *rank* control only ("sort by my number vs the API's number"). **NEW (Emanuel's ask): a "differences only" filter** — one click shows just the companies where ≥1 official figure differs from his number, ordered by largest disagreement first. Ships Tier 3. |

All four rows are now fully decided (2026-06-10); §9 records the resolutions. Nothing remains open.

---

## 0.5 What changed from v1 → v2 (response to Codex)

| Codex finding | Verdict (first-hand) | What v2 does |
|---|---|---|
| **HIGH 1** dual store unsafe/unbuildable | confirmed | **Replaced with a simpler additive design** (§5b/§5c): add ONE read-only `fetched_fundamentals` table; `company_inputs` stays put as the our-view layer. No destructive move, no minted status, no `manual_store.py:280` change, no CSV rewrite, no confidence re-pointing. *(v2.1 went further: the official layer is now a manifest-tracked artifact, §5b — zero store changes at all.)* |
| **HIGH 2** Finder can't use dial frames under current contract | confirmed | §5e defines `CandidateFinderScenario` (keyword param, default `None` = byte-identical to today). Finder dial = Tier 2 (PR3), **in scope, built right after PR2** (Emanuel, 2026-06-10 — the Finder is his most-used tool); the default path stays persisted-spot per completion-plan item 5. |
| **HIGH 3** spot-default is a real refresh change, not config | confirmed | §6 PR1 spells out the exact diff: `cli.py:1805` `include_gold_history=False→True`, mirror Tool D spot-resolve, add 4 columns to the row dict **and** the schema allowlist **and** the REQUIRED set. |
| **HIGH 4** two axes have no output schema | confirmed | §5d defines a frozen `ToolBScenarioBundle` (mirrors `hedge/scenarios.py:47`). **Forward-only in Tier 1**; the official/our-view/trailing sections fill in Tier 3 when their data exists. |
| **HIGH 5** Yahoo pull too hand-wavy | confirmed (gap is *larger* than stated) | §6 PR5 makes auto-pull its own milestone: thin `YahooClient.fetch_financial_statements` + separate `fetch_fundamentals.py` mapper, raw-statement persistence, `/1e6` scale, statement-currency→USD, fixtures US/London/TSX/ASX. |
| **MED 1** rank determinism partial | confirmed | §5g: one parameterized rank helper, `ticker` as the universal final tie-break; **does not** unify Tool B's dense vs Finder's sequential semantics (they genuinely differ). |
| **MED 2** needs instrumentation + cache keys | partially confirmed | §6 PR2 adds `perf_counter` (Tool B serve has none today). Scenario cache is a **separate value-keyed bounded LRU**, not an extension of the file-hash `CandidateFinderCacheKey`. |
| **MED 3** unsafe silent fallback | confirmed (worse than stated) | Hoisted into Tier 1: re-raise `ToolBStaleSchemaError`, derive shown gold from the frame, suppress the lying "recomputing live" banner. |
| **MED 4** serve-boundary guardrails | partially confirmed | §8: clone the Tool-D serve-arithmetic guard (`test_workspace_app.py:1964`) for Tool B — **currently unguarded** — and extend the forbidden-token list to coalesce/ratio/rank-basis. |
| **MED 5** source_verification semantics | confirmed | Folded into HIGH 1: official provenance lives on the new table; `source_verification` stays the user-confidence badge, untouched. |
| **MED 6** phases too big for one PR | confirmed | §6 re-cuts into 3 tiers / 6 PRs, each with ship-value + a test gate + an explicit dependency DAG. |
| **NIT 1** name stale-schema failures | partially confirmed (Codex's framing inverted) | Reality: adding columns does **not** trip the guard — old parquets silently pass, then 500. Fix: add the 3 spot columns to `REQUIRED_TOOL_B_FUNDAMENTAL_COLUMNS` so the calm 503 fires at all 5 read sites (§3, §6 PR1). |
| **NIT 2** precise gold labels | confirmed | `gold_price_basis` enum (`latest_daily_gold_close` / `custom_scenario` / `normalized_3y_avg`); every gold label carries `spot_gold_date`. |
| **NIT 3** no-live-data test boundary | confirmed | §8: two named fake patterns (`_FakeYFinance`/`_FakeTicker` and `_OptionsClient`-style) + committed fixtures under `tests/fixtures/fundamentals/`. |

---

## 0.6 What changed v2 → v2.1 (response to Codex's SECOND pass — each verified first-hand, not just obeyed)

| Codex 2nd-pass finding | Verdict (first-hand) | What v2.1 does |
|---|---|---|
| **HIGH A** PR1 must not persist a fake spot run at 4000 when gold history is unavailable | confirmed — v2's "fallback only when spot unavailable" contradicted its own "fail-loud" | **Adopted with a stronger mechanism than Codex asked for.** Canonical refresh: no valid spot → the Tool B step **fails before persistence** (prior coherent state intact — same fail-closed family as the vendor-outage policy shipped `39074f1`). Custom `--gold-price` runs stay possible but are **structurally isolated**: `persist_tool_b_outputs(..., publish_latest_aliases=False)` — a parameter that **already exists** (`ingestion/persist.py:276`) — so a scenario run writes only run-stamped artifacts and can never become the latest/manifest "current." Plus a belt-and-braces Finder basis guard. See PR1. |
| **HIGH B** Tier 3 lacks a refresh/publish contract for official fundamentals | confirmed — and it exposed a better storage design | **Adopted via an architecture change v2.1 makes itself:** the official layer becomes a **manifest-tracked parquet artifact** (run-stamped + latest alias), NOT a manual-store SQLite table. This answers the refresh contract natively: the model-state manifest is literally a map of `_parquet_artifact(name, path, required_for_complete)` entries (`model_state.py:355-375`) — one new entry, `required_for_complete=False`. Run identity, `fetched_at`, stage timing/rows, a central freshness line, and file-hash cache invalidation (the Finder cache already hashes artifact files) all come from existing machinery. Keeps the manual store purely user-owned. See §2/§5b/PR5. |
| **MED C** Finder section stale vs the staged Bull/Bear cleanup | confirmed (trivially — v2 predates it) | §5e updated: scenario injection covers **all** `TOOL_D_FINDER_FIELDS` (they ride the injected `compute_tool_d_outputs` frame); the 4 resilience criteria DO move under the dial; default-path tests are the new Bull/Bear + Universe ones; **PR3 is sequenced after the staged Finder cleanup lands.** |
| **MED D** status vocabulary split/lossy (`CURRENCY_BASIS_MISMATCH` missing from the bundle enum) | confirmed — real v2 inconsistency | One shared vocabulary + deterministic roll-up defined in §5h.4 (per-field statuses; precedence order; row-level rank-eligibility rule). `§4a`/`§5d` now reference it. |
| **MED E** existing Tool B override controls (thresholds/jurisdiction) undecided | confirmed — they're **threshold** overrides (`screening_overrides.py:28-40`), in-memory only | **Decision made:** gold dial = the primary control; the threshold/jurisdiction overrides move into a collapsed **"Advanced screening assumptions"** panel, mechanically unchanged, same backend recompute + fail-closed path. See PR2. |
| **MED F** PR6 "differences" needs a concrete algorithm | confirmed | Exact field-level algorithm pinned in PR6 (tolerance, denominator rule, zero/negative/missing handling, sort order for unranked differences). |
| **NIT G** explicit reader/schema update line for PR1 | confirmed | One-line rule added to PR1: row dict + `TOOL_B_OUTPUT_COLUMNS` + `REQUIRED_...` change **in the same commit**, and every `validate_tool_b_output_schema` caller (the 5 sites in §3) either renders the new fields or 503s — no partial lands. |

---

## 1. The mental model: three gold prices, only one moves (unchanged, now code-anchored)

| Gold price | What it is | Source | Moved by dial? |
|---|---|---|---|
| **Spot (dated)** | The **latest daily gold close** with its date — NOT an intraday tick. `latest_gold_price_from_history` (`tool_d.py:165-194`) returns `(spot_gold_usd, spot_gold_date)`. | foundation `gold_history` | It is the **default**; the dial starts here. |
| **Scenario** | A price the user picks. | the dial | **Yes** — the only thing the dial changes. |
| **Realized / trailing** | The price that actually prevailed over the trailing 12 months, baked into the auto-pulled TTM financials. | Tier 3 auto-pull | **No** — history can't be re-priced. |

Because spot is a *daily close*, a stale foundation silently yields an old `spot_gold_date`. Therefore **every gold label must render the date** (NIT 2), e.g. `Spot $4,312 (close 2026-06-09)` — this is what makes a stale foundation visible instead of hidden behind the word "spot," and it ties directly to the Phase-1 staleness prerequisite.

---

## 2. The key architecture decision: ADD an official layer, do NOT move the existing one

This is the single biggest change from v1, and it makes the whole dual-source story simpler and safer.

**Verified fact:** `company_inputs` (`manual_store.py:21-34`, table `:514-529`) is one mixed wide table of 11 fields. Codex (HIGH 1) prescribed splitting it: a new `fetched_fundamentals` table **plus** a new `analyst_overrides` table, **physically moving** the 5–6 financial fields out of `company_inputs` with a minted `MIGRATED_MANUAL` status. That move is the expensive, hard-to-reverse part — and it's unnecessary.

**Insight:** every hand-entered financial figure in `company_inputs` **already is** the user's corrected ("our view") number. So:

- **Add exactly one new read-only official layer**, `fetched_fundamentals` (the official Yahoo numbers; this genuinely does not exist today). **v2.1: it is a manifest-tracked parquet ARTIFACT, not a manual-store table** (§5b — answers Codex 2nd-pass HIGH B natively: run identity, freshness line, and cache invalidation all come from existing artifact machinery, and the manual store stays purely user-owned).
- **Leave `company_inputs` exactly where it is** — it is the our-view / override layer. **Zero manual-store schema changes in the entire feature.**
- Resolution is then pure read (no data movement):
  - `Official(field)   = fetched_fundamentals.value` (or `None`)
  - `OurView(field)    = company_inputs.value if present else fetched_fundamentals.value`
  - Operational fields have no official counterpart → `OurView = Official = company_inputs.value` (single source).

**What this deletes vs Codex's first-review design:** the `analyst_overrides` table; the minted `MANUAL_OVERRIDE`/`MIGRATED_MANUAL` status (which `upsert_source_verification` rejects today at `manual_store.py:280`); widening that allow-set; the CSV import/export rewrite (`manual_store.py:472-502`, `:637-760`); and re-pointing `determine_manual_confidence` (`manual_data.py:108-140`), `missing_required_manual_fields` (`:143`), and the serve badges (`detail_forms.py:52-96`) onto a "resolved view." **~5 risky edits → 0.** And with the v2.1 artifact design, even the `CREATE TABLE` goes away: the manual store is not touched at all. Rollback = delete one artifact + its manifest entry → byte-identical store, trivially. Reversibility is provable *by construction*.

> This directly applies the repo's "simplest thing that could work" and "avoid code duplication" rules. It is the recommended design; §9 notes nothing in it conflicts with a locked decision.

---

## 3. Verified code facts (use THESE citations — several of Codex's were stale)

A reference so the implementer doesn't trust drifted line numbers.

**Spot-default plumbing (PR1):**
- `resolve_gold_price` is at **`config_models.py:893-904`** (Codex said `:773` — that's `ScoringConfig.structural_windows`, unrelated). Order: explicit override → `default_gold_price_assumption` (config `4000`) → `gold_price_scenarios[0]`.
- `run_tool_b` resolve call is at **`cli.py:1749`** (def at `:1741`). Foundation load `cli.py:1801-1808` passes **`include_gold_history=False`** (`:1805`) → cannot resolve spot today.
- Tool D contrast: `include_gold_history=True` (`cli.py:1448`); `spot_gold_usd, spot_gold_date = _spot_gold_from_history(...)` (`cli.py:1454`); `resolved = float(gold_price) if gold_price is not None else spot_gold_usd` (`cli.py:1457`). **Tool D also passes `use_model_state` (`cli.py:1451`); Tool B does NOT** `[NEW]` — see §7 cross-tool coherence.
- Tool B row built `pipeline.py:256-305`; frame built with a **hard column allowlist** `pd.DataFrame(rows, columns=TOOL_B_OUTPUT_COLUMNS)` at **`pipeline.py:310`** → any field added to the row dict but not to `TOOL_B_OUTPUT_COLUMNS` (`schema.py:41-86`) is **silently dropped**.
- Tool D emits provenance as real **columns** `tool_d.py:357-360` (`gold_price_used`, `spot_gold_usd`, `spot_gold_date`, `gold_price_delta_vs_spot_pct`) — the Finder reads columns, not parquet attrs, so Tool B must add columns.

**Stale-schema guard (NIT 1 — Codex's framing was inverted):**
- `validate_tool_b_output_schema` (`schema.py:93-113`) raises `ToolBStaleSchemaError` only for **removed** legacy columns or **missing** `REQUIRED_TOOL_B_FUNDAMENTAL_COLUMNS` (`schema.py:26-39`). **Adding** new columns does NOT trip it → old parquets silently pass, then 500 where serve reads a missing column. **Fix:** add the 3 spot columns to `REQUIRED_TOOL_B_FUNDAMENTAL_COLUMNS`.
- Empty-frame short-circuit `schema.py:100-101` returns early → won't false-trip empty-state pages (test this stays true).
- 5 guarded read sites that then fire the calm 503: `workspace_state.py:101` (`/` overview), `overview_tool_d.py:153`, `candidate_finder_data.py:784`, `option_trading_data.py:399`, `cli.py:1468`/`:3308`. Calm 503 copy at `workspace.py:634` ("Run python main.py refresh…"). There is **no `/tool-b` route** — Corporate Finance renders through the workspace.

**Tool B serve override / fail-closed (MED 3, worse than stated):**
- `_resolve_tool_b_frame` reloads foundation+manual every request; **`include_gold_history=False` (`overview_tool_b.py:259`)** and resolves gold via config only (`:269`) → **cannot reach spot on this path** `[NEW]`.
- Bare `except Exception` (`overview_tool_b.py:282-283`) returns persisted **spot** rows **and swallows `ToolBStaleSchemaError`**, while the form still pre-fills the requested non-spot price (`:302`) and renders **"Scenario active: recomputing live"** (`:316-318`) — a banner that **lies** that a recompute happened. Tool D fails safe: `frame.copy()` (`overview_tool_d.py:50`), `active_gold` frame-derived (`:87`), re-raises stale (`:66-67`).

**Candidate Finder (HIGH 2):**
- `load_candidate_finder_data(paths, *, app_config)` — `candidate_finder_data.py:104`, no scenario dim.
- `CandidateFinderCacheKey` `:44-55`, built `:142-154`, from `_file_sha256` of on-disk paths → **in-memory scenario frames have no file to hash** `[NEW mechanism]`. Module-global `_CACHE` `:97`, cleared only by `clear_candidate_finder_cache` → **unbounded** under a continuous dial.
- Tool D forced to spot: `_tool_d_finder_source_path` prefers `tool_d_spot` `:791-803`; `_spot_tool_d_source` `:806-830` blanks **only `tool_d_quality_rank`** (`_blank_tool_d_quality:833-837`) when `|gold_price_used − spot_gold_usd| > 0.01` (`:820-821`). Pinned by **two** tests: `test_candidate_finder_data.py:318` and `:337` (+ missing-Tool-D `:298`; spot-valued fixture `:701`/`:710`).
- Scenario branch must also inject the **Tool B** branch (`:117-131`), not just Tool D, and must re-run `validate_tool_b_output_schema` (`:784`) on injected frames.

**Ranking (MED 1):**
- Tool B: `rank_tool_b_outputs` `ranking.py:8-35`, group `[as_of_date, gold_price_assumption]` (`:18`), **dense** rank of `fundamental_check_score` (`:31-33`); pipeline sort `[as_of_date, gold_price_assumption, fundamental_check_rank, ticker]` `pipeline.py:313-317`, `na_position='last'`.
- Finder: top sort `[percentile, ticker]` `mergesort` `candidate_finder.py:321-325`; final `_sort_rows` `:394-404` (`not rank_eligible, score is None, -score, -top_n_tally, ticker`); `_assign_ranks` `:407-416` is **sequential** (unique 1..N even on ties). → Tool B dense vs Finder sequential **disagree**; only `ticker` is a shared tie-break.

**Yahoo / normalize (HIGH 5 — gap larger than Codex stated):**
- `YahooClient` (`yahoo_client.py:49`) has exactly 4 methods, ending `:81-150`; **no statement fetcher**. Constructor accepts `yf_module=` (`:57`). `fetch_fast_info` returns `{}` on failure (`:127`).
- The only scale logic in the repo: `MINOR_UNIT_CURRENCY_TAGS = {'GBp','GBX','ZAc','ZAX','ILA'}`, ×`0.01` (`price_units.py:8`). `standardize.py:173` keeps `market_cap_usd` only if `currency=='USD'` else `None` (no FX conversion of a money figure). A repo-wide grep for `reporting_currency|statement_currency|fiscal|period_type|statement_scale` hits **only** the plan/review markdown — **zero `.py`**. So statement currency/scale/period is **net-new**, not an extension of the price boundary.
- `[NEW]` yfinance statements are **line-item-name × period-date** oriented (opposite to the per-contract options fixture) → the mapper must transpose / select-by-row-label. And yfinance returns **absolute** currency while fields are `*_musd` → a mandatory **`/1e6`** that is **orthogonal** to the GBp ×0.01 minor-unit scale. v1's "same minor-unit handling as prices" (§B7/Risks) would itself be a bug.

**Reuse templates (named so they're not reinvented):**
- Frozen bundle precedent: `hedge/scenarios.py:47-57` (`CandidateScenarioBundle`).
- Degraded-exclusion gate: Tool D `output['resilience_data_status'].eq('OK')` → NA score → NA rank (`tool_d.py:426-429`); Finder `values.mask(~score_eligible)` (`candidate_finder.py:299-301`).
- Rate boundary: `_rate` `layer2.py:117-123`, `_normalize_numeric_value` `manual_store.py:865-874`, `_normalize_rate` `manual_data.py:250-259` (`>1.0 → /100`).
- Serve-arithmetic guard template: `test_workspace_app.py:1964`/`:1967` (Tool D only — none for Tool B). Stale-schema page test: `:2154`.
- H1 right-reason test template: `test_portfolio_m1.py:839`.
- Live-API isolation: `_FakeYFinance`/`_FakeTicker` `test_yahoo_client.py:57-97` (fast_info as `@property` `:78-81`); `_OptionsClient` consumer fake `test_fetch_options.py:116-148` + committed fixture `:14`.
- Migration input-of-record: `scripts/backfill_manual_data_from_excel.py` (56 tickers × 11 fields, with `source_verification` provenance).

---

## 4. Architecture guardrails (unchanged + reinforced)

- **One EBITDA model, no forked gold math.** All gold recompute funnels through `compute_tool_b_in_memory` (`pipeline.py:121`). Tool D already reuses it (`tool_d.py:107/119/129`); the dial and Finder must too.
- **Backend computes, serve renders.** The dial calls `compute_*_at_gold(G)`; serve does zero gold/ratio/coalesce arithmetic. Enforced by a static-scan guardrail test (§8, MED 4) — currently **absent** for Tool B.
- **No persist on override.** Live recompute is in-memory only; the saved spot parquet is never overwritten.
- **Provenance as real columns** (`gold_price_used`, `spot_gold_usd`, `spot_gold_date`, `gold_price_basis`) — not just parquet attrs, since the Finder reads columns.
- **Instrumented timing.** Add `perf_counter` to Tool B serve (mirror `overview_tool_d.py:55-65`) — it has none today.
- **Single-source thresholds in config** (normalized-gold value, financial-staleness window, EBITDA-reconciliation threshold). No duplicate hardcoded constant.
- **Fail per-item, not per-build.** One bad Yahoo response marks that ticker `financials_unavailable` and continues.
- **Label every gold-dependent number with its gold price + date.**

### 4a. The H1 lesson, made mechanical (not prose)
Degraded/stale/missing data must be **EXCLUDED** from rankings and confident headlines, not just flagged — Phase 1 shipped the flag-only half and it was the review's only HIGH. v2 makes this a concrete reuse, not a promise:

- The bundle (§5d) carries the per-field `value_status` + the deterministic row roll-up defined in **§5h.4** (one shared vocabulary — per-field statuses, precedence order, and the rank-eligibility rule live in `contracts/`, imported everywhere; no second enum).
- Every rank (on either data layer) is produced by the **same `.where(status.eq('OK'))` gate Tool D already uses** (`tool_d.py:426-429`) → a degraded row gets NA rank by construction and sorts last via the existing `na_position='last'`. **No parallel exclude codepath.**
- Resolution feeds status: if Official is degraded but an Our-view override exists, status flips `OK` for Our view, stays degraded for Official.
- Test it **for the right reason** by cloning `test_portfolio_m1.py:839`: an otherwise-healthy ticker (valid beta, valid spot value, present operational inputs) whose **only** defect is degraded financials must be excluded from the affected layer's rank and dropped from the confident headline, **while a second healthy ticker is still ranked** (so a blanked-whole-frame bug fails the test), and the excluded ticker's forward numbers + beta are asserted **still valid** (so exclusion can't pass for an unrelated reason).

---

## 5. The canonical backend contracts (define before any UI)

### 5a. Field catalog — one typed constant, imported everywhere
Mint in `manual_store.py` next to `COMPANY_INPUT_COLUMNS` (today `REQUIRED_MANUAL_FIELDS`, `NUMERIC_COMPANY_FIELDS`, and the `SELECT` each re-list fields — a divergent-copy smell):

```
OPERATIONAL_SINGLE_SOURCE = {production_oz, aisc_usd_per_oz, cash_cost_usd_per_oz,
                             sustaining_capex_musd, reserve_life_years, royalty_rate}
FINANCIAL_DUAL_SOURCE     = {net_debt_musd, ebitda_ltm_musd, interest_expense_musd,
                             da_musd, tax_rate}
```

- `[NEW]` **`da_musd` is in the dual-source set.** v1's auto-pull list omitted it, but `layer2.py:83` consumes it for `forward_net_income`, and D&A is a pure income-statement/cashflow line. Leaving it manual while EBITDA auto-pulls makes the "Our view EBITDA→net income" chain half-stale.
- Completeness invariant test: `OPERATIONAL_SINGLE_SOURCE | FINANCIAL_DUAL_SOURCE == set(NUMERIC_COMPANY_FIELDS)` — so a 12th input can't silently skip classification.
- `fetched_fundamentals` only ever holds `FINANCIAL_DUAL_SOURCE` fields; writing an operational field there raises.

### 5b. `fetched_fundamentals` — a manifest-tracked parquet ARTIFACT, tall (Tier 3) *(v2.1: was a SQLite table; changed in response to Codex 2nd-pass HIGH B)*
One row per `(ticker, field_name)`, columns:
```
ticker · field_name · value
source ('YAHOO') · source_run_id · fetched_at_utc
statement_period ('FY2024') · period_end ('2024-12-31') · period_type ('ANNUAL'|'TTM')
statement_currency · statement_scale          -- audit trail for the /1e6 applied
value_status                                  -- per-field, from the §5h.4 vocabulary
```
- Persisted exactly like every other model artifact: **immutable run-stamped file + `latest` alias**, published by the standard atomic write, under `data/output/fundamentals/`.
- **One new model-state manifest entry** — the manifest is literally a map of `_parquet_artifact(name, path, required_for_complete)` entries (`model_state.py:355-375`); `fundamentals_official` joins it with **`required_for_complete=False`** (a missing/old official layer must never block the price-driven model publish).
- Tall (not wide) so new fields never need a schema change. Written ONLY by the `fetch-fundamentals` stage (PR5); read-only to the user.
- Cache invalidation is free: the Finder cache already keys on `_file_sha256` of artifact paths — the official artifact gets hashed the same way. The manual store file hash (`candidate_finder_data.py:148`) keeps covering the user's layer.
- Raw statements (the receipts, §5h.1) live separately under `data/raw/fundamentals/`, also run-stamped.

### 5c. Resolution rule (no minted status, no overloaded enum)
- `Official` view = `fetched_fundamentals.value`.
- `Our view` = `company_inputs.value if present else fetched_fundamentals.value`.
- `source_verification` (`manual_store.py:36-43`, statuses `VERIFIED/ESTIMATED/INCOMPLETE` only) **stays the user-confidence badge** — never repurposed for provenance (it can't represent it, and overloading it would collide with `detail_forms.py:78-96` and the rollup at `manual_data.py:138`).
- `[NEW]` **`ebitda_ltm_musd` collision pinned:** `OurView(ebitda_ltm_musd)` keeps the hand-entered scalar when present, so the ~56 backfilled tickers' `leverage = net_debt/ebitda_ltm` (`layer1.py:66-70`) is **unchanged** on the Our-view toggle; only Official-view leverage uses the fresh Yahoo figure. §B5's "clean operating EBITDA = operating income + D&A" lands **only in the Official layer**, never overwriting the our-view scalar. Regression test: Our-view leverage byte-identical to today; Official-view differs.

### 5d. `ToolBScenarioBundle` — frozen dataclass (mirror `hedge/scenarios.py:47`)
Row grain today is `(ticker, as_of_date, gold_price_assumption)` with one flat column set. The two new axes become **sections of a bundle**, not extra key columns and not serve-side pairing.

```
@dataclass(frozen=True)
class ToolBScenarioBundle:
    gold_price_used: float
    spot_gold_usd: float
    spot_gold_date: str
    gold_price_basis: str          # latest_daily_gold_close | custom_scenario | normalized_3y_avg
    forward: DataFrame             # gold-MOVING fields (the dial recomputes this)
    rank_column: str               # the single backend-provided rank to sort on
    # Tier 3 adds (empty until then): forward_official, forward_our_view,
    #   trailing_actual, financial_data_status, resolved_display_rows
```

`[NEW]` **Tier 1 ships a forward-ONLY bundle.** The official/our-view/trailing sections model axes that don't exist yet (the trailing-actual EV/EBITDA column literally isn't in `TOOL_B_OUTPUT_COLUMNS` today — `ebitda_ltm_musd` never reaches the output frame). A four-section bundle in Tier 1 would be ¾ empty scaffolding.

**Field partition (derived precisely from the code):**
- **Gold-MOVING → `forward`:** `cash_margin_usd_per_oz`, `margin_pct`, `sustainable_fcf_musd`, `fcf_yield` (`layer1.py:44-65`); `forward_revenue_musd`, `forward_ebitda_musd`, `forward_net_income_musd`, `forward_eps`, `forward_pe`, `ev_ebitda` (`layer2.py:70-96`).
- **Gold-FIXED → never recomputed by the dial:** `leverage = net_debt/ebitda_ltm` (`layer1.py:66-70`), `enterprise_value_musd = market_cap + net_debt` (`layer2.py:91`), all operational inputs, all Tool A betas/returns.
- This asymmetry **is the root of the "3.87 vs Leverage" confusion**: `ev_ebitda` moves with gold but `leverage` does not, and they use *different* EBITDA denominators (`forward_ebitda` vs `ebitda_ltm`). State it so the bundle places them correctly. Lock an invariance test: dialing changes only `forward.*`, never `leverage`.

### 5e. `CandidateFinderScenario` contract (Tier 2)
- `load_candidate_finder_data(paths, *, app_config, scenario: CandidateFinderScenario | None = None)`.
- `scenario is None` → today's exact path verbatim (persisted current artifacts, spot-forced Tool D, the file-hash cache). **Byte-identical**; the two spot-pinning tests (`test_candidate_finder_data.py:318`, `:337`) stay unchanged as the default-path guard.
- `scenario` provided → inject in-memory Tool B **and** Tool D frames (`compute_tool_b_in_memory`, `compute_tool_d_outputs(gold_price=G)`), bypass `_tool_d_finder_source_path`/`_spot_tool_d_source`, re-run `validate_tool_b_output_schema` on injected frames, and **only recompute gold-dependent criteria**.
- `[v2.1 — updated for the staged Bull/Bear Finder cleanup (Codex 2nd-pass MED C)]` **The recompute scope is config-exact** against the NEW criteria set (`config/candidate_finder.yaml` post-cleanup): recompute the gold-moving Tool B criteria `ev_ebitda`, `forward_pe`, `fcf_yield`, `margin_pct` (builder criterion; out of the presets per the merged Finder fix-list R2) — `fundamental_check_score` is **no longer a Finder criterion** and drops out of the enumeration. **Leave unchanged:** `leverage` (gold-fixed), all beta/return criteria, `confidence`, IV criteria, `tool_c_*_rank`, `market_cap`, `aisc`, `reserve_life`.
- `[v2.1]` **Tool D injection covers ALL `TOOL_D_FINDER_FIELDS`** (`candidate_finder_data.py:41-49`), not just `tool_d_quality_rank`: the injected `compute_tool_d_outputs(gold_price=G)` frame carries the 4 resilience fields natively. Expected behavior, locked by tests: `tool_d_quality_rank` **moves** with the dial (its components include leverage-at-G), while the three stress lines + `cost_curve_aisc_percentile` are **scenario-invariant by construction** (the EBITDA line is anchored at spot; cost curve is AISC-only) — add a dial-move invariance test for them, the Tool-D twin of the Tool B `leverage`-invariance test.
- `[v2.1]` The scenario branch must route around `_spot_tool_d_source` with `expected_gold_price=G` semantics (validate the injected frame is at the dialed price; keep blanking on mismatch) so the guard is retargeted, never weakened. Default-path guard tests = the **new Bull/Bear-era tests** (the renamed spot-pinning pair + the `TOOL_D_FINDER_FIELDS` blanking test), kept unchanged.
- Surface scenario provenance: add `gold_price_used`/`source_basis`/`rank_basis` to the returned `CandidateFinderData` dataclass (`:86-94`).
- `[v2.1, belt-and-braces]` Add the cheap **Tool B basis guard**: when the persisted Tool B frame's `gold_price_basis != 'latest_daily_gold_close'`, warn + degrade exactly like `_spot_tool_d_source` does for Tool D (PR1's isolation makes this near-impossible; the guard makes it visible if it ever happens).

### 5f. `financial_data_status` gate — see §4a (reuse Tool D's `.where(status OK)`).

### 5g. Rank helper (MED 1) — parameterized, do NOT unify dense/sequential
`rank(metric_column, orientation: high_good|low_good, eligibility_mask, tie_break='ticker')`:
- NA/degraded metric → excluded, pushed last (Tool B already `na_position='last'`; Finder masks via percentile).
- `ticker` is the **only** universal final tie-break (both engines already agree on it).
- `[NEW]` **Do not** adopt Codex's "secondary `fundamental_check_score`" — neither engine uses it (Tool B's secondary is the dense rank; Finder's is `-top_n_tally`). And **do not** silently unify Tool B's **dense** (`ranking.py:32`) with Finder's **sequential** (`candidate_finder.py:407-416`) — pick per-engine, state it, and if you change one, update its pinned tests.
- Determinism test: `>N` rows with a deliberate **tie** on the ranked metric AND an **NA** metric, recomputed twice at spot and once at a non-spot price, asserting byte-identical order (a test with no ties/NAs is a no-op that passes for the wrong reason).

### 5h. The canonical statement translator (PR5 — FULL SPEC, the load-bearing component)

> This is the make-or-break piece. Yahoo statements do not look like our table: they are oriented **line-item-name (rows) × period-end-date (columns)**, row labels differ by issuer/exchange, EBITDA is usually absent, values are **absolute** (not millions), and foreign names report in their **major** local currency. The translator is the only thing that turns that into trustworthy `*_musd` USD fields — or refuses to, leaving a blank that degrades gracefully. There is **zero** statement-currency/scale/fiscal infrastructure in the repo today; this is net-new and must be its own tested module.

#### 5h.1 Two layers, raw-first (never let `Ticker.*` reach the model)
1. **Thin fetch (in `YahooClient`).** Add `fetch_financial_statements(symbol) -> dict[str, pd.DataFrame]` returning the three raw frames (`income_stmt`, `balance_sheet`, `cashflow`) plus the `financialCurrency` tag. Mirror `fetch_fast_info` exactly: read each statement **as an attribute** inside a `call_with_retries(f"Yahoo statements {symbol}", lambda: self._yf.Ticker(symbol).income_stmt, policy=self._retry_policy, before_attempt=self._rate_limiter.wait)`, and **`return {}` on failure** (the `fast_info` try/except shape at `yahoo_client.py:112-127`), so one bad ticker degrades per-item.
2. **Consumer/mapper (`fetch_fundamentals.py`, new).** Takes an **injected** `YahooClient` (mirror `fetch_options.py:51-58`), never constructs one. (a) persists the **raw** statements untouched to a new `data/raw/fundamentals/` artifact (re-map without re-fetch; audit trail); (b) runs the canonical mapper below; (c) writes the resolved official rows to `fetched_fundamentals` (§5b). **`layer1.py`/`layer2.py` must never import `Ticker.*`** — a guardrail test asserts the model reads only the persisted canonical table.

#### 5h.2 Field-by-field derivation (the alias tables are data WE own and extend against fixtures)
yfinance row labels vary by version/issuer, so these are **candidate label lists to confirm and grow against committed fixtures**, not a fixed contract. Each money field: pick the first matching alias; if a required leg is absent → the field is **`MISSING`** (never coerced to 0).

| Our field | Source statement | Derivation + candidate row aliases (first match wins) | Missing rule |
|---|---|---|---|
| `net_debt_musd` | balance sheet | `total_debt − cash`. **total_debt** = `Total Debt`, else (`Long Term Debt` or `Long Term Debt And Capital Lease Obligation`) + (`Current Debt` or `Current Debt And Capital Lease Obligation`). **cash** = `Cash And Cash Equivalents` (only; do NOT add `Other Short Term Investments` by default — document the choice). If only `Cash Cash Equivalents And Short Term Investments` exists, use it + note. | **No debt leg at all → `MISSING`** (treating absent debt as 0 fabricates a net-cash balance sheet — the most dangerous silent error). No cash row → cash=0 is acceptable (debt-only), but note it. |
| `ebitda_ltm_musd` | income + cashflow | `operating_income + d_and_a`. **operating_income** = `Operating Income` or `EBIT`. **d_and_a** = cashflow `Depreciation And Amortization` or `Depreciation Amortization Depletion`, else income `Reconciled Depreciation`. Capture any reported `EBITDA`/`Normalized EBITDA` separately as `reported_ebitda` for the reconciliation gate (§5h.4) — **do not use it directly**. | operating_income or d_and_a missing → `MISSING`. |
| `da_musd` | cashflow | the **same** `d_and_a` used in EBITDA (kept consistent). | missing → `MISSING`. |
| `interest_expense_musd` | income | `abs(` `Interest Expense` or `Interest Expense Non Operating` `)` (store as positive). | missing → `MISSING` (a real $0 interest is rare for a miner; prefer MISSING + note over assuming 0). |
| `tax_rate` | income | **v1: keep MANUAL** (see §10). If later pulled: `Tax Provision / Pretax Income`, through `_rate`. | Pretax Income ≤ 0, or ratio outside `[0,1]` (loss/credit year) → **degraded, NOT silently `/100`'d** (the `_rate >1.0→/100` rule would corrupt a 1.5 into 0.015). |

#### 5h.3 Normalization order (each step is separate and tested)
For every **money** field, in this order:
1. **Read raw** (absolute, in `financialCurrency`).
2. **Currency → USD.** If `financialCurrency == 'USD'` → rate `1.0`; else `merge_fx_asof(value_frame, date_column=period_end, fx_history=fx_history[financialCurrency])` (`normalize/calendar.py:26`) and multiply. **Statements are in the MAJOR currency (`GBP`/`AUD`/`CAD`), never pence** — so the `GBp ×0.01` minor-unit scaling (`price_units.py:8`) **MUST NOT** be applied to statements. That conflation (v1 §B7/Risks) would itself be a bug.
3. **Scale → millions.** `÷ 1_000_000` (yfinance returns absolute currency; our fields are `*_musd`). This is **orthogonal** to step 2 — both must happen, exactly once each. Record the applied factor in `fetched_fundamentals.statement_scale`.
4. **Rates** (`tax_rate` if ever pulled): through the existing `_rate`/`_normalize_rate` helper (single boundary, no copy), with the loss-year guard above.
5. **Shares**: a count — no currency, no `÷1e6`.

#### 5h.4 ONE status vocabulary + a deterministic roll-up *(v2.1: unified in response to Codex 2nd-pass MED D — v2 had `CURRENCY_BASIS_MISMATCH` outside the bundle enum, leaving two engineers free to disagree)*

**Per-FIELD `value_status`** — one shared enum, defined once in `contracts/` and imported by the mapper, the bundle, and serve formatting:
`OK | MISSING | STALE | CONTAMINATED | CURRENCY_UNCONVERTIBLE | CURRENCY_BASIS_MISMATCH`
- All required rows present, currency known & convertible, period fresh → **`OK`**.
- A required leg missing → **`MISSING`** (never coerced to 0 — §5h.2).
- `period_end` older than the config staleness window → **`STALE`** (gate on `period_end`, the data's age, **not** `fetched_at`, our call recency — else a fresh pull of an 18-month-old annual passes).
- Reconciliation fails (§5h.5) → **`CONTAMINATED`**.
- `financialCurrency` not in our FX universe → **`CURRENCY_UNCONVERTIBLE`**.
- `financialCurrency` ≠ the snapshot `feed_currency` and not a clean conversion → **`CURRENCY_BASIS_MISMATCH`** → flag for human (dual-listing/ADR; never auto-convert blindly — EV is only valid if market cap and debt share a currency basis).

**Roll-up to the row/metric level** (deterministic, no judgment calls in serve):
1. A metric is **Official-rank-eligible** iff **every field it consumes is `OK`** — the same `.where(status.eq('OK'))` gate Tool D uses (§4a). Any non-OK consumed field → NA rank, sorts last. `CURRENCY_BASIS_MISMATCH` and `CURRENCY_UNCONVERTIBLE` therefore ALWAYS exclude Official EV/leverage ranks — by the rule, not by special-casing.
2. The row's displayed `financial_data_status` badge = the highest-precedence non-OK status among consumed fields, precedence: `CURRENCY_BASIS_MISMATCH > CONTAMINATED > MISSING > CURRENCY_UNCONVERTIBLE > STALE` (worst-first; each renders a plain-English badge).
3. **`FINANCIALS_UNAVAILABLE`** is the whole-ticker case only (no usable statements at all) — it is a ticker-level flag, not a field status.
4. Our-view interplay unchanged (§4a): a user override on a field makes that field's *Our-view* status `OK` regardless of the official status; the Official side keeps its real status.

#### 5h.5 Reconciliation gate (catches "present but wrong," not just "missing")
When **both** a `reported_ebitda` (Yahoo's own) and our computed `operating_income + d_and_a` exist: if `abs(reported − computed) / computed > ebitda_reconciliation_max_pct` (single-sourced config, §4a) → mark `CONTAMINATED` → degraded → excluded, and surface **both** numbers + the divergence % in the badge. A large gap almost always means a mis-mapped row, a wrong scale, or a one-off lump (the Orla "Other income/expense −$119M" case).

#### 5h.6 Period model
Each statement column is a `period_end`; use the most recent. **v1 uses the latest ANNUAL statement** (`period_type='ANNUAL'`, labelled `FYxxxx`) — simplest correct. A clearly-marked later refinement computes **TTM** by summing the last 4 quarterly columns for flow items (income/cashflow) while balance-sheet items (debt/cash) stay point-in-time from the latest balance sheet. Stamp `fetched_at_utc`, `period_end`, `period_type` distinctly (§5b).

#### 5h.7 Fixtures + tests (no live calls — NIT 3)
Commit raw-statement fixtures under `tests/fixtures/fundamentals/`, paralleling `tests/fixtures/options/`, for: a **US** name (clean USD), a **London `.L`** name (`GBP` + split-debt + the scale trap), a **TSX `.TO`** (`CAD`), an **ASX `.AX`** (`AUD`), plus edge fixtures — **missing-debt-leg**, **reported-EBITDA-divergent**, **negative-pretax**. Tests:
- `fetch_financial_statements` retry/rate-limit/degrade-to-`{}` via a `_FakeYFinance`/`_FakeTicker` exposing `income_stmt`/`balance_sheet`/`cashflow` as `@property` (mirror `test_yahoo_client.py:78-81`).
- Mapper per-field correctness on the US fixture; **alias fallback** on a fixture lacking `Total Debt` (split legs); **missing-leg → `MISSING`, never 0**; **CAD fixture → same USD as a pre-converted control**; `÷1e6` applied exactly once; **pence-vs-`/1e6` non-conflation** on the London name; reconciliation flags the divergent fixture; negative-pretax → tax degraded not `/100`'d.

#### 5h.8 Two worked examples
- **US clean (Orla-style):** balance sheet `Cash And Cash Equivalents = 36,000,000`, no debt rows present-but-zero → `net_debt = 0 − 36,000,000 = −36,000,000` → `÷1e6 = −36 musd` (this matches the **−36** net-debt we just saw in Orla's saved runs — a good sanity anchor). EBITDA = `Operating Income + Depreciation And Amortization`.
- **London pence trap:** `financialCurrency = 'GBP'` (the statement is in pounds, **not** pence). Convert via `merge_fx_asof(..., fx_history=GBP)` on `period_end`, then `÷1e6`. The `GBp ×0.01` price rule is **not** applied — applying it would make every figure 100× too small.

#### 5h.9 Explicitly out of scope for v1
Quarterly-TTM reconstruction (use latest annual first); auto-resolving `CURRENCY_BASIS_MISMATCH` (flag, don't guess); auto-pulling `tax_rate` (stay manual); algorithmic one-off "cleaning" beyond the reconciliation flag (exclude, don't clean).

---

## 6. Tiered PR plan (ship-value + test-gate + dependency DAG)

**Dependency DAG (nothing starts before its blocker):**
```
completion-plan Phase 0 (publish) + Phase 1 (staleness)
        └─> PR1 (persist-at-spot columns)
                ├─> PR2 (Tool B dial)  ──> PR3 (Finder scenario) ──> PR6 (Official|Our-view UI)
                └─> [stale-schema 503 lands at all 5 read sites BEFORE any reader uses new cols]
        PR4 (official-artifact contract + loader) ──> PR5 (Yahoo ingestion + mapper + refresh stage) ──> PR6
```
PR1/PR2 touch the **Tool B parquet schema**; PR4/PR5 add a **new artifact + stage** (zero manual-store changes, zero Tool B schema changes) — disjoint surfaces, so Tier 1 and Tier 3 can proceed on independent branches without collision. **PR3 additionally waits for the staged Bull/Bear Finder cleanup to be fixed (merged fix-list) and committed** — its contract is the new Finder, not yesterday's.

### TIER 1 — "Spot truth" (fixes the entire stated confusion)

**PR1 — Persist Tool B at dated spot, fail closed, isolate scenario runs.** *(prereq: completion-plan Phase 1 staleness)*
- `cli.py:1805` `include_gold_history=False→True`; mirror Tool D spot-resolve (`cli.py:1454-1457`).
- `[v2.1 — Codex 2nd-pass HIGH A, adopted]` **The canonical refresh NEVER falls back to config gold.** No `--gold-price` override + `_spot_gold_from_history` returns no valid close (missing/empty gold history, no positive close) → **the Tool B step FAILS before any persistence**, leaving the prior coherent model state intact — same fail-closed family as the vendor-outage policy (`39074f1`). "Valid" = `latest_gold_price_from_history` returns a value; no second date-window gate (foundation freshness already governs age, and the date is visible on every label per §1). `resolve_gold_price`/`default_gold_price_assumption=4000` survives ONLY for explicit custom runs and legacy serve-override parsing — it is never a spot substitute.
- `[v2.1]` **Custom `--gold-price` runs are structurally isolated:** they persist run-stamped artifacts only, via the **existing** `persist_tool_b_outputs(..., publish_latest_aliases=False)` parameter (`ingestion/persist.py:276,301`) and never update the model-state manifest current pointer — so a scenario run can never become the "latest" the Finder/workspace consume. Stamp them `gold_price_basis='custom_scenario'`.
- Add `spot_gold_usd`, `spot_gold_date`, `gold_price_used`, `gold_price_basis` to the row dict (`pipeline.py:256`) **and** `TOOL_B_OUTPUT_COLUMNS` (`schema.py:41`) **and** `REQUIRED_TOOL_B_FUNDAMENTAL_COLUMNS` (`schema.py:26`) — **in the same commit** (the frame builder is a hard allowlist, `pipeline.py:310`: a field missing from the columns list is silently dropped). `gold_price_basis='latest_daily_gold_close'` for the canonical run.
- `[v2.1 — Codex NIT G]` **Reader contract, one rule:** every `validate_tool_b_output_schema` caller (the 5 sites in §3: `workspace_state.py:101`, `overview_tool_d.py:153`, `candidate_finder_data.py:784`, `option_trading_data.py:399`, `cli.py:1468/:3308`) either renders the new fields or surfaces the calm 503 — no reader may partially consume the new schema.
- Wire `use_model_state` into Tool B's foundation load (`cli.py:1801`) to match Tool D (`cli.py:1451`) — see §7 coherence.
- **Ship value:** "Open the tool — every gold number is at today's dated close, not $4,000. If gold data is missing, the tool says so and keeps yesterday's good state."
- **Gate:** persisted `gold_price_used == spot_gold_usd` with `basis='latest_daily_gold_close'`; **a no-override run with missing gold history fails BEFORE persistence and the previous artifacts + manifest are untouched** (new test); **a `--gold-price` run leaves `tool_b_latest` + the manifest byte-identical** and writes only run-stamped scenario files (new test); an old parquet lacking spot columns trips the **calm 503** (clone `test_workspace_app.py:2154`) at each of the 5 read sites; empty-frame short-circuit still returns early (`schema.py:100-101`).

**PR2 — Tool B in-memory gold dial (forward-only bundle).**
- New frozen `ToolBScenarioBundle` (§5d, forward section only); `compute_tool_b_at_gold(G)` returns it, no persist, with provenance + timing.
- Dial on the Corporate Finance page (mirror `overview_tool_d.py:188-223`): presets from config (`Spot`, scenario ladder) + custom box + URL param; date-stamped labels (§1).
- **Hoist the Tier-1 safety fixes** (MED 3): re-raise `ToolBStaleSchemaError` instead of the bare `except` swallow (`overview_tool_b.py:282`); derive shown gold from the frame's `gold_price_used` (`overview_tool_d.py:87` pattern) not `overrides.gold_price`; suppress the "recomputing live" banner on failure; change the serve override path to `include_gold_history=True` + `latest_gold_price_from_history` so it can actually reach spot.
- Add `perf_counter` instrumentation split `load/compute/render` (mirror `overview_tool_d.py:55-65`).
- `[v2.1 — Codex 2nd-pass MED E, decided]` **The existing Tool B override controls get an explicit home.** They are *screening-threshold* overrides (AISC max, P/E max, FCF-yield min, margin min, reserve-life min, leverage max, tier discounts — `screening_overrides.py:28-40`), in-memory only, a different axis than the gold price. PR2: the **gold dial becomes the page's primary control**; the threshold/jurisdiction controls move into a collapsed **"Advanced screening assumptions"** `<details>` panel — mechanically unchanged, same backend recompute, same fail-closed rules (a combined gold+threshold recompute failure snaps BOTH back to the persisted basis). Tests: advanced panel collapsed by default; the dial works with no advanced inputs; combined overrides recompute once (not twice).
- **Ship value:** "Move one dial — the whole table recomputes and re-ranks at any gold price, with a live timer; the $4,000 confusion is gone."
- **Gate:** dial-move re-rank determinism (§5g); dial does not change Tool A betas (guardrail); `leverage` invariant to the dial; **clone the Tool-D serve-arithmetic guard for Tool B** (§8); fail-closed test (no non-spot box + lying banner over spot rows).

### TIER 2 — "Finder coherence" *(IN SCOPE — Emanuel, 2026-06-10: the Finder is his most-used tool; build immediately after PR2 AND after the staged Bull/Bear Finder cleanup is fixed + committed — PR3's contract is the new Finder, not yesterday's)*

**PR3 — `CandidateFinderScenario` contract** (§5e). Default path byte-identical; scenario path injects in-memory Tool B+D frames; separate bounded value-keyed scenario cache (§5d perf / not the file-hash key).
- **Ship value:** "The Finder dial recomputes only gold-dependent criteria; the default Finder stays the coherent spot view."
- **Gate:** the Bull/Bear-era default-path guards unchanged (the renamed spot-pinning pair + the `TOOL_D_FINDER_FIELDS` blanking test) + scenario-path tests: injected non-spot `tool_d_quality_rank` flows through un-blanked; **all four resilience fields ride the injected frame** (and the three stress lines + cost curve are dial-invariant — §5e); scenario cache key differs from default; `scenario=None` key byte-identical.
- **Status (Emanuel, 2026-06-10): UN-PARKED — build right after PR2.** Initially deferred, then revisited when Emanuel clarified the Finder is his primary tool. Two clarifications from that discussion, recorded so the framing stays honest: (a) the risk here is **data-contract plumbing, not math placement** — Finder math is fully backend (`model/candidate_finder.py`; the page module `serve/candidate_finder_page.py` only formats, verified first-hand) and stays that way; (b) **PR1 alone already fixes the Finder's daily numbers** (it screens at persisted spot automatically once Tool B persists at spot) — PR3 adds the hypothetical-price re-screen ("who survives at $3,000?") on top.

### TIER 3 — "Dual source" (a separate data project)

**PR4 — Official-artifact contract + loader** (§5b/§5c — v2.1: an artifact, not a table): define the `fetched_fundamentals` parquet artifact (columns per §5b incl. per-field `value_status`), its `data/output/fundamentals/` home (run-stamped + latest alias, atomic publish), the `fundamentals_official` model-state manifest entry (`required_for_complete=False`, extending the `_parquet_artifact` map at `model_state.py:355-375`), the shared `value_status` enum in `contracts/` (§5h.4), the field catalog (§5a), and the loader/resolution rule (`Official = artifact value`; `OurView = company_inputs if present else artifact`) reading through the manifest.
- **Gate:** the manual store is **byte-identical before/after** (zero schema or row changes — assert the store file hash unchanged across the PR's tests); a missing/absent official artifact degrades to "no official data" everywhere (loader returns an empty official frame; `required_for_complete=False` keeps the model state COMPLETE); deleting the artifact + manifest entry restores pre-PR behavior exactly; resolution-rule unit tests (override-wins, official-fills, operational-fields-single-source).

**PR5 — Yahoo statement ingestion + canonical mapper.** **Built to the FULL SPEC in §5h** (the load-bearing component). In brief: thin `YahooClient.fetch_financial_statements` (returns `{}` on failure) + a separate `fetch_fundamentals.py` consumer that persists raw statements first, then maps via the §5h.2 alias tables, normalizes in the §5h.3 order (currency→USD via `merge_fx_asof`, then `÷1e6`, kept separate from the GBp price scale), applies the §5h.4 status tree + §5h.5 reconciliation gate, and writes `fetched_fundamentals`. `layer1/layer2` never import `Ticker.*`.
- `[v2.1 — Codex 2nd-pass HIGH B, adopted]` **The refresh/publish contract, explicit:**
  - A **named stage with its own CLI command**: `python main.py fetch-fundamentals` — NOT bolted into the nightly `update-data` for v1 (statements move quarterly; ~60 tickers × 3 statements per run is real Yahoo load; a config cadence/flag can fold it into `update-data` later). Run it manually or weekly.
  - The stage gets a normal **`RunContext`**: run id, per-step **timing + row counts** self-reported into the run summary (`soul.md` #4 — "where did the time go" answerable for free), per-ticker status summary (OK/degraded counts).
  - Outputs: run-stamped raw statements (`data/raw/fundamentals/`) + the run-stamped official artifact + latest alias + the `fundamentals_official` manifest entry carrying `source_run_id` and `fetched_at_utc`.
  - **Central freshness:** the alignment/freshness check gains one line — official-fundamentals age (from the artifact's `fetched_at_utc`, window single-sourced in config). It **warns**, never blocks the price-driven publish: the official layer is explicitly **outside the all-or-nothing model publish** (`required_for_complete=False`), like the manual store. Rank-level staleness is separately enforced per field by `value_status=STALE` (gated on `period_end` — §5h.4), so a stale official layer is *visible centrally* AND *excluded from Official ranks* — flag AND exclude, both.
  - Cache coherence: the official artifact's file hash joins the Finder/Tool B cache keys exactly like every other artifact (`_file_sha256` pattern).
- **Gate:** the §5h.7 fixture suite (US/London/TSX/ASX + missing-leg + divergent-EBITDA + negative-pretax), all no-live-call; missing-leg→`MISSING`-not-0; pence-vs-`/1e6` non-conflation; per-item degrade never aborts the pull; **stage summary contains per-step seconds + rows; manifest entry written; freshness line fires on an artificially old `fetched_at_utc`.**

**PR6 — Market-vs-Ours comparison view (per the revised §0.4).** Backend emits resolved columns (`ev_ebitda_official`, `ev_ebitda_our_view`, `ev_ebitda_trailing` (display-only), `leverage_official`/`leverage_our_view`, `financial_data_status`, plus per-ticker **`divergent_field_count`** and **`max_divergence_pct`**); serve renders three things and computes none of them: (1) the always-visible **"Market \| Ours" pair** on EV/EBITDA + Net Debt/EBITDA wherever the user's figure differs from Yahoo's (identical → single number, no clutter); (2) the **"Rank by: [Our view \| Official]"** control — re-sorts on the backend-provided rank column for that layer; names with no official data get NA rank → sort last under Official; (3) the **"differences only" filter** (`divergent_field_count > 0`), ordered by `max_divergence_pct` descending so the biggest disagreement tops the list.
- `[v2.1 — Codex 2nd-pass MED F, adopted]` **The difference algorithm, pinned (backend-only, per dual-source FIELD):**
  - A field **differs** iff an override exists AND `not math.isclose(ours, official, rel_tol=1e-6)` — compared **after** both values pass the same normalization boundary (so a units artifact can never register as a disagreement).
  - `field_diff_abs = ours − official`; `field_diff_pct = abs(diff_abs) / abs(official)` **only when `abs(official) > 0`**; when `official == 0` or non-finite → `field_diff_pct = None` and the field is flagged "different (no % basis)" — **never** divide by ours, never substitute a tiny denominator (Codex's exact worry: a near-zero denominator out-ranking a real disagreement).
  - Per ticker: `divergent_field_count` = count of differing fields; `max_divergence_pct` = max over fields **with a defined pct** (None if none defined).
  - **Sort order of the "differences only" view:** defined-pct rows first, `max_divergence_pct` descending; then no-%-basis rows (still shown, badged); `ticker` final tie-break. Fields with a non-OK official `value_status` (§5h.4) are **not** counted as disagreements — you can't "disagree" with a number we don't trust; the badge says so instead.
  - All of it computed in the backend and emitted as columns; serve filters/sorts only — locked by the extended serve guardrail test.
- **Gate:** both ratios computable Official vs Our-view from one row; the pair renders **only** where an override differs; the filter returns exactly the override-differing tickers in the pinned sort order (test includes an `official=0` row and a near-zero-denominator row proving neither out-ranks a genuine large disagreement); rank-by-Official excludes no-official names via NA-last; serve guardrail extended to forbid coalesce tokens; the H1 right-reason exclusion test (§4a); the "never overwrite" invariant in both directions (re-fetch doesn't clobber an override; a user edit doesn't mutate the official artifact).

---

## 7. New production-safety ideas `[NEW — neither v1 nor Codex raised these]`

1. **Currency-mixing assertion in EV/leverage (highest-probability silent break).** `enterprise_value_musd = market_cap_musd + net_debt_musd` (`layer2.py:91`) and `leverage = net_debt/ebitda_ltm` (`layer1.py:66-70`) consume money scalars with **no currency check**. It works today only because a human typed USD. The moment `net_debt` auto-pulls from a CAD/GBp/AUD balance sheet, EV becomes "USD market cap + foreign-currency debt" → plausible-but-wrong. **Fix:** the canonical table tags `statement_currency`; the mapper converts to USD on the statement date; `layer1/layer2` assert USD (or mark `financials_unavailable`) before arithmetic. Fixture test: a TSX name with CAD net debt yields the same EV as the same name pre-converted to USD.
2. **EBITDA reconciliation gate (catches "present but wrong," not just "missing").** When both a yfinance-reported EBITDA and our `operating income + D&A` exist, if `abs(divergence)/our_ebitda` exceeds a config threshold (`ebitda_reconciliation_max_pct`, single-sourced), mark the official EBITDA `CONTAMINATED` → degraded → excluded, and show both numbers + the % in the badge. Catches a mis-mapped row, wrong scale, or a one-off lump (the Orla −$119M case) automatically.
3. **Statement-period vs fetch-date staleness.** Store `fetched_at` (when we pulled) **and** `period_end`/`period_type` (what the figure covers) separately. yfinance silently returns the latest available statement — during a reporting gap, a 12–18-month-old annual masquerading as current. The staleness window (§4a) must gate on `period_end` (data age), not `fetched_at` (call recency) — else a fresh pull of stale data passes. Badge: "Yahoo FY2024 (period end 2024-12-31), pulled 2026-06-09."
4. **Cross-tool spot coherence.** Tool B does not pass `use_model_state` (`cli.py:1801`) while Tool D does (`cli.py:1451`) → after PR1, Tool B "spot" and Tool D-spot can resolve from different foundations and differ by a day's gold move, and the Finder would rank Tool B valuation at one spot against Tool D quality at another. **Fix:** wire `use_model_state` into Tool B (PR1) + add a cross-tool assertion in `candidate_finder_data.py` that Tool B `spot_gold_usd == Tool D-spot` within the existing 0.01 tolerance, else surface a "spot mismatch across tools" warning rather than silently joining.
5. **Dual-listing currency mismatch.** Gold miners are heavily dual-listed (TSX+NYSE, LSE+JSE). When `statement_currency != snapshot feed_currency` (already tracked in `NORMALIZED_MARKET_SNAPSHOT_COLUMNS`), flag `currency_basis_mismatch` for human resolution rather than blindly converting — EV is only valid if share count and debt share a currency/entity basis.
6. **Degraded financials = NA-rank-sorts-last in ONE table, not a bespoke page-state.** Reuse the existing NA-rank-last behavior (`overview_tool_b.py:107-113`, blank rank cell `:123`): a degraded name shows a blank rank + muted "no reported financials" tag, while its forward @gold numbers (from operational inputs + price) still render. Same H1-exclusion correctness, no new vocabulary for a beginner.
7. **Bound the scenario cache.** A continuously-dragged dial turns the unbounded module-global `_CACHE` (`candidate_finder_data.py:97`) into a slow leak. Use a `~32`-entry `OrderedDict` LRU for scenario results (or bypass `_CACHE` entirely and debounce the dial). Round `gold_price` to cents in any key to stop float-churn.

---

## 8. Test catalog (what to clone, no-live-data boundary)

- **H1 right-reason exclusion** → clone `test_portfolio_m1.py:839` (second-healthy-ticker control + still-valid-beta assertion).
- **Serve-arithmetic guard for Tool B** → clone `test_workspace_app.py:1964`/`:1967` for `overview_tool_b.py`; extend forbidden tokens to coalesce (`.combine_first(`, `.fillna(`, `'fetched'`, `'analyst_override'`), ratio pairing (`net_debt_musd /`, `enterprise_value`, `ev_ebitda =`), and rank-basis branching; assert the positive (`compute_tool_b_in_memory` imported, no mapper/coalesce helper imported).
- **Rank determinism** → §5g (ties + NAs, spot + non-spot, byte-identical).
- **Stale-schema calm 503** → clone `test_workspace_app.py:2154` at the 5 read sites; + empty-frame no-false-trip.
- **Fail-closed dial** → on simulated recompute failure: shown gold == frame's `gold_price_used` (spot), "recomputing live" banner absent, `ToolBStaleSchemaError` re-raised to the 503 handler.
- **Default-path Finder guards** → keep `test_candidate_finder_data.py:318` & `:337` unchanged; add scenario-path + cache-key-uniqueness tests.
- **Financial edge cases** → negative/zero EBITDA → `n/a`+excluded; net-cash (negative net_debt) ranks sanely + labeled; **missing one leg of net debt → MISSING, never coerced to 0** (fabricates strength); no-official-baseline → Official excludes, Our-view includes iff override; dial below AISC → forward EBITDA negative → `n/a` + margin/leverage tags fire (`tool_d.py:442-445`).
- **Unit boundary** → Yahoo `tax_rate` 0.21 stays 0.21 and 21.0→0.21 through the **existing** `_rate`/`_normalize_rate`; a loss-year ratio `>1.0` is flagged degraded, not silently `/100`'d; London name gets currency-convert **and** `/1e6` exactly once each, in order.
- **No-live-data boundary (NIT 3):** the new `fetch_financial_statements` is unit-tested with a `_FakeYFinance`/`_FakeTicker` exposing `income_stmt`/`balance_sheet`/`cashflow` as `@property`; the mapper is tested via an `_OptionsClient`-style consumer fake reading **committed** fixtures under `tests/fixtures/fundamentals/` (US/London/TSX/ASX). No test calls Yahoo statements live.

---

## 9. RESOLVED (Emanuel, 2026-06-10) — the three §0-touching simplifications

All three were put to Emanuel and decided; §0's table carries the outcomes. For the record:

- **(A) ADOPTED — side-by-side, not a display toggle.** An always-visible **"Market | Ours"** pair on EV/EBITDA and Net Debt/EBITDA, rendered only where the user's figure differs from Yahoo's. The layer toggle survives **as the rank control only** ("Rank by: Our view | Official") — which is exactly Emanuel's "sort by my number vs the API's number" ask. Plus his new ask: a **"differences only" filter** — one click shows just the names where his numbers disagree with Yahoo's, biggest gap first. The disagreement list *is* the research agenda.
- **(B) ADOPTED — one ranking rule.** Forward metrics at the dialed gold, on the selected layer; trailing is a labeled display column, never a sort basis. Emanuel's own instinct ("how do we decide the trailing period? it could change everything") is precisely the reason: a trailing rank inherits the trailing-period choice (§5h.6), so we don't rank on it.
- **(C) ADOPTED as a full CUT — no @normalized column.** Emanuel doesn't find it useful; the dial reaches any price. The `gold_price_basis` enum keeps the door open at zero schema cost.

---

## 10. Open knobs — all CLOSED (2026-06-10)
- `tax_rate`: **manual with override — LOCKED (Emanuel agreed 2026-06-10).** Deriving `tax provision / pre-tax income` is the noisiest field — loss years/credits push the ratio `>1.0` where the `_rate` helper silently corrupts it, and a founder can't sanity-check a tax rate 100× too small.
- `da_musd`: auto-pull (it's a clean income-statement line; §5a).
- ~~Normalized-gold default~~: **CUT with §0.3** — no normalized column, no 3-yr-average build-time computation, no config knob. Nothing remains open.

## 11. Risks (updated)
- **Stale spot** → hard dependency on completion-plan Phase 1; date-stamped labels make a stale foundation visible (§1).
- **Rank jitter** → §5g determinism tests with ties + NAs.
- **Currency-mixing in EV/leverage** → §7.1, the highest-probability *silent* break.
- **`/1e6` vs GBp ×0.01 scale conflation** → §3 HIGH 5, a guaranteed wrong number if missed.
- **Prior-year statement masquerading as current** → §7.3 period-end staleness.
- **Losing a layer** → eliminated by construction: the official layer is a separate read-only artifact and the user's layer is the untouched manual store; there is no migration at all, and rollback = delete one artifact + manifest entry.
- **Cross-tool spot divergence** → §7.4.
- **Repeating H1** → §4a makes exclusion a reuse of Tool D's proven `.where(status OK)` gate, not a prose promise.
