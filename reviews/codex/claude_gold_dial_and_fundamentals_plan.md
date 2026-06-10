# Plan — Gold price dial (spot by default) + auto-pulled fundamentals

**Author:** Claude Code (Opus 4.8), for Codex review then implementation on `dev-vic`.
**Status:** DRAFT for Codex review.
**Plain-English goal:** When you open the tool, every gold-dependent number should be at **today's actual gold price** (not a hardcoded $4,000). You should be able to move a single **gold dial** to any price and have the whole table recompute and re-rank. And the fundamentals the tool relies on (net debt, trailing EBITDA, revenue, etc.) should be **pulled automatically from published financials** where Yahoo has them — with manual override — instead of all being typed by hand, while the gold-specific operational inputs (AISC, production, cash cost) stay manual.

This plan solves the same root confusion behind the "EV/EBITDA = 3.87 looks wrong" question: the multiple looked off because (a) it was computed at a fixed $4,000 peak-gold assumption, and (b) the trailing EBITDA it was compared against was a stale hand-entered number.

---

## 0. Locked product decisions (confirmed by Emanuel)

1. **Saved run = spot.** The overnight pipeline persists all gold-dependent metrics at **today's live spot gold**. Other prices (normalized, $3,000, etc.) are computed **live in memory** when the dial moves — never persisted. (Matches Tool D today.)
2. **Ranking = a toggle.** On valuation pages the user can switch the ranking basis between:
   - **"At chosen gold price" (forward-modeled)** — re-sorts as the dial moves; apples-to-apples at one gold price.
   - **"Actual reported (trailing)"** — fixed; does **not** move with the dial; "what am I really paying today."
3. **Layout = one dial + compact pair.** A single gold dial sets the whole table and re-ranks it. For the 2–3 valuation metrics (EV/EBITDA, FCF yield, forward P/E) also show a small **"@spot | @normalized"** pairing so peak-gold cheapness is always visible — without doubling every column.
4. **Keep BOTH the official and the user's numbers — never overwrite; compare them.** The auto-pulled (Yahoo/API) figure and the user's own corrected figure are **both stored** per field. The official number is never replaced by an edit. The user can then compare "what the market sees" (official Net Debt/EBITDA) against "what we think is more accurate" (our corrected ratio). The comparison itself is the product value. (This supersedes the earlier "manual override wins / skip auto-pull" wording — we keep both.)
   - **Ranking layer = a toggle (LOCKED, Emanuel 2026-06-09).** The whole-table **"Numbers: [Official | Our view]"** control (§B6) drives **both** the displayed numbers **and** the ranking — flip it and the table re-sorts on that layer. Default starting position = **Our view** (best estimate, official always shown beside as the benchmark), but the user can switch to Official at any time and the rank follows. (This is the data-source axis; it composes with the gold-price rank-basis toggle in §0.2 / §A4.)

---

## 1. The mental model: three gold prices, only one moves

| Gold price | What it is | Source today | Moved by the dial? |
|---|---|---|---|
| **Spot** | Today's live price (~$4,300) | Fetched + dated every refresh (`fetch_gold.py`, `_spot_gold_from_history` `cli.py:2667`, `latest_gold_price_from_history` `tool_d.py:167`) | It is the **default** the dial starts at |
| **Scenario** | A price the user picks ($2,500, $3,000…) | The dial | **Yes** — this is the only thing the dial changes |
| **Realized / trailing** | The price that actually prevailed over the last 12 months | Baked into the **auto-pulled TTM financials** (Workstream B) | **No** — it is history; you cannot re-price the past |

**Consequence:** the dial moves only the **forward-modeled** numbers (EBITDA/EV-EBITDA/FCF/margins at the chosen price). The **trailing-actual** column is fixed history. This separation is what keeps "two sets of numbers" clean rather than tangled.

---

## 2. The ranking rule (the hard part)

> **A ranking is only valid if every name in it was computed at the same gold price.**

So when the dial moves, the **whole displayed universe recomputes and re-ranks together** — never a partial mix of prices. Tool D already enforces this; we extend it.

Two boundaries that MUST be respected:

- **Tool A (the beta charts) does NOT move with the dial.** Betas come from weekly return regressions; they depend on gold *returns*, not the gold *level*. The dial must not touch Tool A, the lenses, or any return-based metric. (Same "scope it tightly" discipline Codex applied to `score_eligible`.)
- **The trailing-actual column does NOT move with the dial** (§1). When the ranking toggle (§0.2) is set to "actual reported," moving the dial recomputes the forward columns for display but **leaves the rank order unchanged**; only the "at chosen gold price" toggle re-sorts on dial moves.

---

## 3. What already exists vs. what we build

**Already built (we reuse, do not reinvent):**
- Spot gold fetched + dated every refresh.
- **Tool B is already gold-parameterized** — `layer2.py:70` computes revenue/margin/EBITDA from `gold_price_assumption`. It is simply being fed the config `4000` instead of spot.
- **Tool D's full live-override pattern** — `compute_tool_d_outputs(gold_price=G)` (`tool_d.py:89`): recompute in memory, **no persist**, presets via `tool_d_stress_scenario_presets` (`tool_d.py:152`), provenance stamped (`gold_price_used`, `spot_gold_usd`, `gold_price_delta_vs_spot_pct`), recompute time instrumented and shown.
- A **config scenario list** already exists (`config/screening_params.yaml`: `gold_price_scenarios: [3000,3500,4000,4500,5000]`).
- A **Candidate Finder spot-gold guardrail** already checks the upstream Tool D run was at spot (`candidate_finder_data.py:809-827`).
- A **per-field provenance table** already exists (`source_verification` in `manual_store.py`) for "auto vs manual, with source URL/date."

**What we build:** generalize Tool D's pattern to Tool B + Candidate Finder, flip the default from $4,000 → spot, add the auto-pull ingestion + trailing-actual column, and the rank toggle + layout.

---

## 4. Architecture guardrails (do not violate)

- **One EBITDA model, no forked gold math.** All gold-dependent recompute funnels through the single Tool B model (`layer2.py` / `compute_tool_b_in_memory`). Tool D already reuses it; Tool B's dial and the Finder dial must reuse the same function, never a copy. (We just removed forked gold-shock math in the audit — do not reintroduce a parallel path.)
- **Backend computes, serve renders.** The dial calls a backend `compute_*_at_gold(G)`; the serve layer does zero gold arithmetic (same rule Tool D's review verified). Add a guardrail test that the new serve code contains no EBITDA/margin formula tokens.
- **No persist on override.** Live dial recompute is in-memory only; the saved spot parquet is never overwritten by a scenario.
- **Provenance stamped everywhere.** Every gold-dependent row (saved or served) records `gold_price_used`, `spot_gold_usd`, and `basis` (`forward_modeled` | `trailing_actual`). Extend Tool D's existing provenance fields to Tool B + Finder.
- **Instrumented timing.** Show "recomputed in X.XXs" on dial moves (Tool D already does — measure the real recompute, don't assume it's fast).
- **Config, not ad hoc.** Preset prices and the normalized value live in `config/screening_params.yaml`. No hardcoded prices in code (Golden Vector rule #2).
- **Label every gold-dependent number with its gold price.** The unlabeled $4,000 is what caused the EV/EBITDA confusion.

### 4a. Lessons folded in from the Phase 0/1/2 review (apply on this new data surface)
Each maps to a finding from `reviews/codex/claude_review_completion_phases_1_2.md`. The auto-pull is a brand-new data surface where these same mistakes will recur unless designed in:
- **Degraded data is EXCLUDED from confident outputs + rankings, never just flagged (H1).** Phase 1's H1 was stale-FX lines that were flagged yet still counted in the confident measured-exposure headline. The same rule binds here: any number whose source is stale / missing / unreliable / one-off-contaminated (stale or missing auto-pulled financials, `financials_unavailable`, a contaminated trailing EBITDA) must be **excluded** from confident valuation headlines AND from any ranking — or routed to an explicit "Degraded financials" state — not silently ranked as if solid. See §B3b.
- **Single-source every threshold in config (M1).** Phase 1's M1 was a `0.10` gate hardcoded in one place and config-driven in another → silent drift. Every new threshold here (the normalized-gold value, the financial-staleness window, any IV/quality cap) lives once in `config/`, read by all surfaces; no hardcoded constant that duplicates a config value.
- **Fail per-item, not per-build (M3).** Phase 1's M3 let one bad lot abort the whole build. The auto-pull must degrade **per ticker** — one bad/empty Yahoo response marks that ticker `financials_unavailable` and the refresh continues; never abort the whole fundamentals pull or portfolio build.
- **Currency/units through the ONE standardize boundary (the refuted finding).** Phase 1's currency "finding" was *refuted precisely because* pence/unit handling is centralized upstream in `standardize`/`normalize`. Keep it that way: foreign financials in their reporting currency are normalized at that same boundary, never via an ad-hoc string compare.
- **Tests must prove behavior, not pass for the wrong reason (test-fidelity lessons).** Phase 1's stale-FX test passed only because the line also had a sub-floor beta. Here: the degraded-financials exclusion test must use an **otherwise-healthy** stock (so it's excluded for the *right* reason); re-rank determinism is tested with **>N rows**; user-facing strings (the "@spot | @normalized" pair, "Market | Our view", degraded badges) are asserted at the **serve-render** level, not just the frame.

---

## PHASE A — The gold dial (ships independently, using current manual fundamentals)

### A1. Default the saved run to spot
- Resolve **spot** (from `_spot_gold_from_history`) and pass it as the `gold_price_assumption` for the **persisted** Tool B / screening run, replacing the config `4000` default for the canonical run.
- Keep `default_gold_price_assumption` in config as a **fallback only** (used if spot is unavailable/stale), and rename its role in comments to "fallback when spot missing." Do **not** delete it.
- Stamp `gold_price_used` + `spot_gold_usd` + `spot_gold_date` into the persisted Tool B parquet (mirror Tool D).
- **Dependency:** "spot" must be the **fresh** spot. This requires the staleness fix (completion plan Phase 1) so the foundation the run reads is the latest refresh, not a stale pinned one. **A1 must land after Phase 1** (or the spot default will silently use stale gold).

### A2. Add the dial to Corporate Finance (Tool B)
- Backend: `compute_tool_b_outputs(gold_price=G)` (or extend the existing in-memory entry) returning the full table recomputed at G, **no persist**, with provenance + timing — mirror `compute_tool_d_outputs`.
- Serve: a gold dial on the Corporate Finance overview, default = spot, presets from config (`Spot`, `Normalized`, plus the existing scenario ladder), plus a custom price box. URL param carries the selected price so views are shareable (mirror Tool D's lens param).

### A3. Add the dial to Candidate Finder
- Candidate Finder ranks on criteria; **only the gold-level-dependent criteria recompute** (valuation/EBITDA/FCF/margin). Beta/return criteria are untouched (§2).
- Reuse the existing spot-gold provenance guardrail (`candidate_finder_data.py:809`) — but now it must also accept **non-spot** runs when the dial is explicitly moved (today it warns "not a spot-gold run"). Distinguish "saved default should be spot" (warn if not) from "user moved the dial" (expected).
- Measure the recompute time over the full universe; if it exceeds an interactive budget, precompute the **config preset** prices and compute only custom prices live with a visible timer. **No silent caps** — if anything is precomputed-only, say so.

### A4. The ranking toggle (§0.2)
- A control on Tool B + Finder valuation views: **"Rank by: [At chosen gold price ▼ | Actual reported (trailing)]"**.
- "At chosen gold price" → rank by the forward-modeled metric at the dial's price; **re-sorts on dial moves.**
- "Actual reported (trailing)" → rank by the trailing-actual metric (Workstream B); **does not re-sort on dial moves** (the dial still updates the forward columns for display).
- Until Phase B lands, "Actual reported" uses the existing manual `ebitda_ltm_musd` (flagged as hand-entered); after B it uses the auto-pulled TTM. Document this clearly so the toggle isn't misread as "real" while still manual.
- **Degraded-data rule (§4a/§B3b):** when ranking by "Actual reported", a stock with stale/missing/degraded trailing financials is **excluded** from the ranking (shown in a "Degraded financials" state), not ranked on absent numbers.

### A5. The compact valuation pair (§0.3)
- For EV/EBITDA, FCF yield, forward P/E: show **"@spot | @normalized"** side by side, each labeled with its gold price. The rest of the table follows the single dial.
- **Normalized value (LOCKED, Emanuel 2026-06-09):** a config knob `normalized_gold_price_assumption`. **Default = the trailing 3-year average of the gold history we already fetch, computed at build time** (grounded in real history, auto-updates, not a magic number). The config field accepts either `auto-3y` (the computed average) or an explicit fixed number, so it stays overridable. Single-sourced in config (§4a/M1) — no hardcoded fallback that can drift. Label the column with the actual normalized price used (e.g. "@ $2,950 (3-yr avg)").

### A6. Phase A tests
- Re-rank-at-price is deterministic + stable (documented tie-breaks; no jitter on repeated recompute).
- Moving the dial does **not** change Tool A betas / lens / return metrics (guardrail test).
- "Actual reported" rank order is invariant to the dial; "At chosen gold price" rank re-sorts.
- Saved run is at spot (provenance asserts `gold_price_used == spot_gold_usd`); override does not write parquet.
- Serve layer contains no gold arithmetic (static-scan guardrail).
- Every gold-dependent served value is labeled with its gold price.

---

## PHASE B — Auto-pull published fundamentals (the hybrid)

### B1. Field split — what auto-pulls vs stays manual

**Auto-pull from Yahoo financials (currently hand-entered → make automatic):**
| Field | Source | Note |
|---|---|---|
| `net_debt_musd` | balance sheet: total debt − cash & equivalents | the stale-leverage culprit |
| `ebitda_ltm_musd` (trailing-actual) | income stmt operating income + cash-flow D&A (or yfinance normalized EBITDA) | feeds the "Actual reported" rank basis |
| `interest_expense_musd` | income statement | |
| trailing revenue, trailing net income, diluted shares, tax provision | income statement | new trailing-actual display fields |

**Stay manual (NOT in standard financials — power the gold scenarios, come from production reports):**
`production_oz`, `aisc_usd_per_oz`, `cash_cost_usd_per_oz`, `sustaining_capex_musd`, `reserve_life_years`, `royalty_rate`.

(`tax_rate` can be derived from tax provision ÷ pre-tax income, or stay manual — Codex's call; default: derive with manual override.)

### B2. New Yahoo fetch
- Add `fetch_financials(symbol)` to `yahoo_client.py` (it has no financials method today) pulling `.income_stmt` / `.balance_sheet` / `.cashflow`. Rate-limited like the other fetchers; resilient to missing/partial data.
- New ingestion step that maps raw statements → the B1 auto fields, writing the **official** values to a dedicated table (§B4) — **never into the user's `company_inputs` table.**

### B3. Coverage — be honest about the limit
- Yahoo financials are reliable for the ~24 **US-listed** names but **patchy for the foreign small-caps** (London/AUD/CAD) — which is most of the book.
- Per ticker: attempt auto-pull; if Yahoo returns missing/zero/obviously-corrupt statements, **store no official value and flag it** `financials_unavailable`. For those names "Our view" simply has no official baseline to compare against (single-source).
- **Degrade per ticker, never per-build (M3 lesson, §4a):** one ticker's bad/empty/throwing Yahoo response marks only that ticker and the pull continues; it must not abort the whole fundamentals refresh.

### B3b. Data-quality & freshness gate — carry the H1 lesson onto financials (§4a)
- Every auto-pulled number carries `source_date`. Define a **financial-staleness window** in config (single source — §4a/M1). A figure older than the window, missing, or one-off-contaminated is **degraded**.
- A stock with degraded/missing **trailing** financials is **excluded from the "Actual reported (trailing)" ranking and from confident valuation headlines** (shown in an explicit "Degraded financials" state with its local/forward numbers still visible) — never silently ranked on stale or absent reported numbers. This is Phase 1's H1 fix transplanted: **flag AND exclude, not flag-only.**
- "Our view" can still be computed for a degraded stock if the user has supplied a manual correction (the correction is trustworthy even when Yahoo is stale) — degraded applies to the *official* layer; a user override clears it for that field.

### B4. Store BOTH layers — official and our view (the core of §0.4)
**Both numbers must persist and be independently computable. The official figure is never overwritten by a user edit.**

- **Official layer (new table, e.g. `fetched_fundamentals`):** `ticker`, `field_name`, `value`, `source` (`YAHOO`), `source_date`, `reporting_currency`. Written only by the auto-pull step (B2). Read-only to the user.
- **Our-view layer (the existing `company_inputs` / a parallel `analyst_overrides`):** holds the user's own figures, optional per field, each with a free-text **reason/note** (reuse the `source_verification` `notes`/`source_url`, status `MANUAL_OVERRIDE`).
- **Resolution rule:**
  - **"Official" view** = pure `fetched_fundamentals` value.
  - **"Our view"** = `coalesce(analyst_override, fetched_fundamentals)` — official everywhere the user hasn't corrected, the user's figure everywhere they have.
- **Both views are always computable**, so every gold-dependent metric (Net Debt/EBITDA, EV/EBITDA, …) can be produced **twice**: once on Official, once on Our view. Neither layer is ever destroyed.
- **UI:** per field, a small badge — "Yahoo, <date>" and, if corrected, "your figure (was $X)" with the reason on hover.
- **Migration note:** today `company_inputs` mixes hand-entered financials *and* operational inputs. The migration must (a) move existing hand-entered financial fields into the our-view layer (they are corrections, not official), and (b) leave operational inputs (AISC, production, …) where they are — those are single-source with no official counterpart (§B1).

### B5. Normalization of one-offs
- Raw financials carry lumps (e.g., Orla's TTM "Other income/expense" −$119M). The **trailing-actual EBITDA** must be a clean operating figure (operating income + D&A), **excluding** non-operating one-offs. Document the exact rule; do not feed raw net income into EBITDA.
- EBITDA is not reported directly — compute it; if using yfinance "normalized EBITDA," record that as the source basis.

### B6. Wire both layers into the views — Market vs Our view
- The trailing-actual column (from B1) becomes the fixed companion to the forward-modeled column (§1) and the "Actual reported" rank basis (§A4).
- **Two independent comparison axes that compose** (§0.4):
  1. **Gold price** — spot ↔ chosen (the dial), affects forward-modeled metrics only.
  2. **Data source** — Official (market) ↔ Our view (with corrections), affects which fundamentals feed every metric.
- **UI:** a whole-table **"Numbers: [Official | Our view]"** toggle (mirrors the gold dial), default position **Our view** (§0.4). **This toggle drives BOTH the displayed numbers AND the ranking** — flip it and the table re-sorts on that layer (LOCKED §0.4). On the key leverage/valuation ratios (Net Debt/EBITDA, EV/EBITDA) show a compact **"Market | Our view"** pair always visible — same pattern as the "@spot | @normalized" gold pair, so the comparison is on-screen without toggling.
- **UX note — three controls compose, keep them sane.** The page now has the gold dial (price), the rank-basis toggle (§A4, forward vs trailing), and this data-source toggle. Group them in one clear control bar with sensible defaults (spot · at-chosen-gold · Our view) so the page is useful and correctly-ranked **without touching anything**; every control is labeled and the table always states which gold price + which layer it's showing.
- **EV/EBITDA clarity outcome:** show **trailing-actual EV/EBITDA** (real reported) next to **forward EV/EBITDA @ selected gold**, both labeled — and each computable on Official vs Our view. This resolves the 3.87 confusion *and* surfaces "the market underestimates this company's leverage" when your corrected debt differs from Yahoo's.

### B7. Phase B tests
- Auto-pull maps statements → fields correctly on a fixture; missing/zero statements → no official value + `financials_unavailable` flag.
- **Both layers persist independently:** a user correction writes to the our-view layer and does **NOT** mutate `fetched_fundamentals`; the official value is still readable after the edit.
- **Resolution rule:** "Official" view = pure fetched; "Our view" = override-where-present-else-fetched; a single corrected field changes only that field in Our view.
- **Both ratios computable:** Net Debt/EBITDA and EV/EBITDA each produce an Official number and an Our-view number from the same row.
- Normalization strips the one-off (fixture with a large "other income/expense" → EBITDA excludes it).
- Currency/units: foreign financials respect the same minor-unit handling as prices (guard against a pence-style ÷100 bug in reported figures — verify reporting currency).
- Provenance row written with correct status + date + reason note.
- **Degraded-data exclusion (H1 transplant, §B3b):** an **otherwise-healthy** stock (good beta, valid spot value) whose trailing financials are stale/missing is **excluded** from the "Actual reported" ranking + confident valuation headline — assert it's excluded for the *right* reason (degraded source), not masked by another gate. Per-ticker degrade does not abort the build.
- **Threshold single-sourcing (M1 transplant):** assert the normalized-gold value and the financial-staleness window come from config, with no duplicate hardcoded constant (e.g. a drift-guard equality test where applicable).

---

## 5. EV/EBITDA — the concrete before/after

- **Before:** one unlabeled EV/EBITDA at a fixed $4,000 forward EBITDA (~$959M), compared on the page against a *different*, stale, hand-entered trailing EBITDA (~$500M) behind "Leverage." Looked like 3.87 with no context.
- **After:** **Trailing-actual EV/EBITDA** (from the real pulled TTM EBITDA, ~$750M for Orla) **next to** **Forward EV/EBITDA @ spot** and **@ normalized**, each labeled with its gold price; "Leverage" uses the same pulled trailing EBITDA. One coherent set of numbers, no stale hand-entered figure. And where the user has a better debt/EBITDA figure than Yahoo, the page shows **Market vs Our view** for that ratio — so the gap between what the market sees and what you believe is explicit (§0.4 / §B6).

---

## 6. Sequencing

1. **Completion plan Phase 0 (publish discipline) + Phase 1 (staleness fix)** — prerequisite. A1's "spot default" is only correct once the run reads the fresh foundation.
2. **Phase A** (gold dial) — ships independently using current manual fundamentals. Order: A1 → A2 → A4 → A5 → A3 → A6.
3. **Phase B** (auto-pull) — upgrades the "Actual reported" basis from stale-manual to real-pulled, and lights up the trailing-actual EV/EBITDA. Order: B1 → B2 → B3/B4 → B5 → B6 → B7.

Phase A is valuable alone (current-gold default + dial + labeling fixes most of the confusion). Phase B removes the remaining manual-data staleness.

---

## 7. Open knobs for Emanuel
- ~~**Normalized gold price**~~ — **DECIDED (2026-06-09): trailing 3-year average, auto-computed, config-overridable** (§A5).
- ~~**Default ranking layer**~~ — **DECIDED (2026-06-09): a toggle (Official | Our view) that drives both display and ranking; default position Our view** (§0.4 / §B6).
- **`tax_rate`** (§B1): derive from financials, or keep manual? (Minor — Codex's call; default: derive + manual override.) Still open but low-stakes.

---

## 8. Risks / things that could go wrong
- **Stale spot.** If Phase 1 isn't done, "default to spot" silently uses stale gold. Hard dependency.
- **Rank jitter.** Live re-ranking must be deterministic (stable sort, fixed tie-breaks) or the table flickers on the dial.
- **Recompute cost on Finder.** Measure the real time over the full universe; fall back to precomputed presets + live custom with a visible timer; never silently truncate.
- **Foreign financials currency/units.** Auto-pulled reported figures must respect reporting currency + minor-unit handling (same family of bug as LSE pence).
- **One-off contamination.** Trailing EBITDA must exclude non-operating lumps, or the "real" number is as misleading as the old one.
- **Forked math regression.** All gold recompute must funnel through the single Tool B model — no parallel copy.
- **Losing a layer.** A user edit must never overwrite the official fetched value, and a re-fetch must never overwrite a user correction — the two layers are separate tables (§B4). The migration that splits today's mixed `company_inputs` must not silently reclassify an operational input as a "correction" or vice-versa.
- **Repeating H1 on a new surface (the biggest one).** Degraded auto-pulled financials must be EXCLUDED from rankings + confident headlines, not just flagged — Phase 1 shipped the flag-only half of exactly this and it became the review's only HIGH. Designed in via §4a + §B3b; lock it with the §B7 exclusion test.
- **Threshold drift (M1 recurrence).** New thresholds (normalized gold, freshness window) must be single-sourced in config or they drift like Phase 1's min-beta gate did.
