# Claude review — Codex "Corporate Finance Source Mode Usability Plan"

**Reviewer:** Claude (first-hand code reads + a 59-agent map→adversarial-verify fleet; 47/53 findings confirmed).
**Plan reviewed:** `reviews/codex/corporate_finance_source_mode_usability_plan.md`
**Verdict:** **APPROVE WITH MAJOR REFRAMING.** The plan's *intent* is right and its fundamentals current-state claims are accurate. But its biggest flaw is that **a large part of what it proposes already ships** — it must be rewritten as "extend the existing Our-View/Official system," not "build a new `fundamentals_source` toggle." The genuinely-new parts (provenance, calc popover, per-source verdict, rolling to the other surfaces, historical fundamentals) are valid and well-scoped. The two plans (this + horizon consistency) **can be coded in parallel with specific guardrails** — see §5.

---

## 1. Source-mode recomputation

### 1a. HIGH — Most of this is already built; reframe as "extend," not "build"
A shipped two-source system already exists and the plan barely acknowledges it:
- `golden_vector/fundamentals/resolution.py:28-101` — `resolve_fundamental_layers()` already resolves **Official(Yahoo) vs Our-view** per field (`official_value/status/source`, `our_view_value/status/source`). This is exactly the "existing fundamentals resolution layer" the plan says to reuse — it exists.
- `golden_vector/screening/pipeline.py:366-388` — already computes + persists `ev_ebitda_our_view`/`_official`, `leverage_our_view`/`_official`, `enterprise_value_musd_our_view`/`_official`, plus `_differs` flags. Schema requires them (`screening/schema.py:34-38, 89-98`).
- **Per-source rank/score/summary already persisted:** `fundamental_check_rank_official`, `fundamental_check_score_official`, `fundamental_check_summary_official`, `fundamental_checks_passed_official`/`_total_official`.
- `golden_vector/serve/overview_tool_b.py:66-86` — `_comparison_numeric_td()` already renders the "Ours / Market" dual cell when `{metric}_differs`.
- `overview_tool_b.py:117, 165-168, 819-838` — a `rank_by` dropdown (**Our view / Market**) already switches the displayed rank between `fundamental_check_rank` and `fundamental_check_rank_official`; `differences_only` + `divergent_field_count` + `max_divergence_pct` already filter/sort by divergence.
- The request-time recompute precedent exists: `_resolve_tool_b_frame` → `compute_tool_b_in_memory` (the gold-dial scenario tool) already recomputes Tool B per request when overrides are present.

**Fix:** rewrite the plan to (a) reuse `resolution.py` (do NOT add a second resolution path), (b) reuse the `{metric}_our_view`/`_official`/`_differs` columns and `fundamental_check_rank_official`, (c) treat `fundamentals_source=our|yahoo` as a **thin alias/rename of the existing `rank_by` + recompute machinery**, not a new system, and (d) **rename the UI label "Market" → "Yahoo Fundamentals"** (more accurate — `official` is the Yahoo-mapped layer). Running `fundamentals_source` *and* `rank_by`/"Market" as two parallel vocabularies would be a real mess.

### 1b. HIGH — Per-source **verdict** is the genuine gap (rank/score are done, verdict isn't)
`screening_verdict` exists but there is **no `screening_verdict_official`** (`screening/pipeline.py:322-347`, `schema.py`). So the plan's "recompute verdict per source" is real and missing. **Fix:** produce `screening_verdict_official` in the model where `fundamental_check_rank_official` is produced (the verdict is derived from the checks, so it's a cheap extension) — in the model, never in serve.

### 1c. MEDIUM — The 26-field "shared metric object" is new, but must emit the existing flat columns
The current contract is flat (`{metric}_our_view/_official/_differs`); `overview_tool_b.py` reconstructs the comparison from those. The plan's rich object (`metric_id`, `active_value`, `formula`, `components`, …) is genuinely new (`schema.py:58-125` has none of it). **Fix:** build it incrementally — the resolution layer should emit the new structured object **alongside** the existing flat columns (back-compat), starting with `net_debt`, `ebitda`, `ev_ebitda`, `leverage`. Don't big-bang-replace the flat schema.

### 1d. MEDIUM — `compute_tool_b_in_memory` has no `finance_source` parameter
`screening/pipeline.py:160-173` — the in-memory recompute can't yet select Our-view vs Yahoo. **Fix:** add a `finance_source: Literal["our","yahoo"]` parameter that selects which resolved layer feeds Layer 1/2, and thread it through. This is the single backend hook the whole feature hangs on; design it first (Phase 2), reuse everywhere (Tool B, candidate finder, Tool D).

---

## 2. Yahoo provenance (direct vs derived)

### 2a. HIGH — Provenance is genuinely missing AND the plan's model doesn't match the code's real branches
`golden_vector/fundamentals/mapper.py:159-205` (`_map_net_debt`) computes net debt **one way** — `total_debt - cash`, where `total_debt` is either a direct `Total Debt` field **or** `long_debt + current_debt`. It **never checks for a direct Yahoo `netDebt` field** (the plan's central example), discards the components, and exposes no origin flag. `_MappedField` and `FETCHED_FUNDAMENTALS_COLUMNS` have no provenance columns. Same for `_map_ebitda` (`mapper.py:208-263`): it computes `operating_income + DA`; a direct `EBITDA` field is used **only for reconciliation validation, not tracked**.

So the plan's idealized axis ("direct `netDebt` field vs derived") **does not match reality** — the code's real provenance axes are: (i) `total_debt` direct field vs `long+current` summed, (ii) EBITDA direct-field-exists-but-unused vs `operating_income+DA`, (iii) **cash-missing-assumed-zero** (already encoded in `statement_scale = "..._cash_missing_assumed_zero"`). **Fix:** reconcile the plan's provenance model with what Yahoo/yfinance + the code actually provide; build on the existing `statement_scale` provenance signal; only add a "direct `netDebt`/`EBITDA` field" path if you actually fetch+map those fields (today they aren't mapped).

### 2b. HIGH — Components are discarded; the popover can't be built without capturing them
`_map_net_debt` collapses to a single number and throws away `total_debt`, `cash`, `long_debt`, `current_debt`. `_find_value` (`mapper.py:378-389`) also discards **which** `line_item_original` it matched. The plan's `i`-popover (formula + Yahoo fields used + component values) is impossible without these. **Fix:** add an optional `components` payload to `_MappedField` (list of `{field_name, yahoo_line_item, value, status}`) and make `_find_value` return the matched label. Persist it for the historical artifact too.

### 2c. Are the proposed provenance fields enough? — Mostly yes, with two adjustments
`yahoo_value_origin`, `direct_yahoo_value`, `derived_yahoo_value`, `direct_vs_derived_differs`, missing-input status, and a calc explanation are **sufficient** for the UI — provided (1) `components` carries the **per-component unit/currency** (mixed-currency rule: the popover must show normalized values in the page unit), and (2) `yahoo_value_origin` includes the **`cash_missing_assumed_zero`** state that already exists, so a "partial" net debt isn't shown as a clean "calculated from Yahoo fields." Also add `ebitda` provenance (LOW today, but leverage = `net_debt/ebitda` inherits it — `layer1.py:66-70`).

---

## 3. Historical Yahoo fundamentals

The plan's **current-state claims are accurate** (verified first-hand + fleet): `raw_statement_payload_to_frame` preserves every `period_end` (`raw_store.py:~291`), `fetch_financial_statements` is annual-only (`ingestion/yahoo_client.py:140-163`, no `freq`/`quarterly_*`), and `map_raw_fundamentals_to_official` is latest-only via `_latest_statement_rows` (`mapper.py:365-375`). The "separate historical artifact, defer analytics/UI" framing is the right call. Prerequisites the plan correctly implies but which **do not exist yet**:

- **HIGH — `period_type` missing from raw schema (collision risk).** `RAW_FUNDAMENTALS_STATEMENTS_COLUMNS` (`contracts/fundamentals.py:59-72`) has no `period_type`, and `_flatten_statement_frame` doesn't infer ANNUAL/QUARTERLY from the yfinance `freq`. Adding quarterly **without** `period_type` would let FY2025 and Q4 2025 (both ending 2025-12-31) collide. Must land **before** any quarterly fetch. Bump `RAW_FUNDAMENTALS_STATEMENTS_SCHEMA_VERSION`.
- **HIGH — separate history artifact not present.** Only `fetched_fundamentals_latest_path`/`_run_stamped_path` exist (`contracts/fundamentals.py:80-116`); no `fetched_fundamentals_history_*` columns/version/path. Add them as the plan specifies; keep the latest decision artifact untouched (Tool B reads it).
- **MEDIUM — merge/dedupe-upsert + `row_hash` + first/last/changed-seen not built.** `raw_store.py`/`artifacts.py` write fresh every time (`drop_duplicates(['ticker','field_name'], keep='last')`). Build a `fundamentals/history_store.py` that loads prior history, hashes rows, upserts, and **preserves older periods when Yahoo returns a shorter frame** (the plan's key durability rule). 
- **LOW — coverage tracking + separate refresh cadence config missing.** `ticker_statuses` records only pass/fail (`fetch.py:45`); add per-ticker period-range coverage for the "FY2021–FY2025" label. `AppConfig.fundamentals` has `refresh_fetch_max_age_days` but no `history_refresh_interval_days` — add one so history doesn't fetch intraday.

Period modeling (period_type/period_end, stable keys, dedupe/upsert, preserve-older) is **sound as designed**; confirm this is a **separate artifact**, which the plan correctly mandates.

---

## 4. Architecture safety

- **MEDIUM (not the HIGH the plan implies) — "no finance in serve" is already nuanced here.** The plan treats request-time finance recompute as forbidden, but the **sanctioned** gold-dial pattern already calls `compute_tool_b_in_memory` from serve (`candidate_finder_data.py:1053-1068`; Tool D calls it 3× at `tool_d.py:103,115,125`). That's a *model* function invoked from serve, not finance-in-render — which is allowed. **Fix:** the source-mode recompute should **reuse** that path (add `finance_source` to `compute_tool_b_in_memory`), NOT pre-persist dual-source scenario artifacts (over-engineering for a request-time scenario view). Keep the existing serve-arithmetic guardrail green (no new formula fragments in render code).
- **HIGH (possible pre-existing bug — flag for confirmation) — Tool D's internal Tool B may run on empty fundamentals.** The fleet found Tool D's internal `compute_tool_b_in_memory` calls don't pass `official_fundamentals`, while the main Tool B call does (`candidate_finder_data.py:1054` vs `tool_d.py` internal calls). If true, Tool D resilience is computed on **default/empty** fundamentals today — a real inconsistency independent of this plan. **Please verify and fix regardless of the source-mode work.**
- **All-or-nothing / model-state:** the plan respects it (recompute is request-level, never publishes from a UI toggle — explicitly stated). Good. The new history artifact must publish through the same manifest/all-or-nothing path.
- **Duplicated helpers:** the main risk is a second source-resolution path. Mandate reuse of `resolution.py` + the existing `_official`/`_our_view` columns.

---

## 5. Conflict with my horizon-consistency plan — **parallel is possible, with guardrails**

The two plans live mostly in **different subsystems**: horizon = Tool A scoring/windows (`model/scoring.py`, `model/pipeline.py`, `serve/windows.py`→`common/windows.py`, `overview_tool_a.py`); source-mode = Tool B/fundamentals (`screening/`, `fundamentals/`, `overview_tool_b.py`). Real collision points:

| Collision | Files | Risk | Mitigation |
|---|---|---|---|
| **Detail page** | `serve/detail_panels.py` | HIGH (same big file) — but **different functions**: horizon owns the Tool A panels/scorecards/explanation cards/window switcher (~1050–1313); source-mode owns the "Latest Corporate Finance Snapshot" (`:226`, `_render_latest_panels`) | Agree an explicit **function-ownership split** in `detail_panels.py`; neither refactors the other's region. Integrate this file with the spine-merge protocol (commit small, rebase often, adversarially verify the page where a window switcher AND a `fundamentals_source` toggle will coexist). |
| **URL/query state** | new `serve/url_helpers.py` | MEDIUM — both add a URL param (`window=` vs `fundamentals_source=`) and must preserve existing params | Whoever lands first creates ONE shared `build_page_url(...)` helper; the other reuses it. Don't write two param-builders. |
| **Window registry** | `common/windows.py` | LOW — source-mode doesn't need windows, but both edit serve URL/query plumbing | Horizon Phase 1 (registry) is independent; source-mode need not wait on it. |
| **Overview pages** | `overview_tool_a.py` vs `overview_tool_b.py` | LOW — different files; per the locked scopes, overviews get the **window** selector (horizon) but **not** the source toggle (source-mode scope excludes overviews) | No action; just don't add source-mode to overviews (prevents 5×2 column explosion). |

**Verdict:** **Yes, code them in parallel** — they're in separate subsystems and the model layers don't overlap (Tool A pipeline vs Tool B screening pipeline; Tool A scoring vs fundamentals resolution). The only file needing active coordination is `serve/detail_panels.py` (function-ownership split) and the shared URL helper. Given our "merge-the-spine-before-milestones" rule, I recommend: **(a)** both proceed on `dev-vic` with small, frequent commits; **(b)** lock the `detail_panels.py` ownership split + the shared `url_helpers.py` up front; **(c)** whoever touches `detail_panels.py` or the URL helper commits it first and the other rebases; **(d)** a joint adversarial check on the detail page once both a window switcher and a `fundamentals_source` toggle render together. If you want **zero** integration risk instead, isolate one of them in a git worktree and merge at its first milestone — but I judge parallel-with-guardrails as safe here.

---

## 6. Other findings (LOW/NIT)
- **NIT** — `ingestion/yahoo_client.py:131-135` docstring doesn't state the statements are annual-only; add it.
- **LOW** — `differences_only` (`overview_tool_b.py:161-187`) is a view filter, not source-aware; fine to keep, just don't conflate it with the source toggle.
- **LOW** — candidate-finder link helpers (`candidate_finder_page.py:161-171, 621-635`) must carry `fundamentals_source` once it exists (Phase 6) — same shared URL helper.
- **LOW** — `_CandidateFinderScenarioSources` (`candidate_finder_data.py:121-129`) has no `fundamentals_source` field to label "Candidate result: Yahoo Fundamentals"; add it.

## 7. Final verdict
**Approve with major reframing.** Sequence: (1) **rewrite the plan** to extend the shipped Our-View/Official system (reuse `resolution.py` + `_official` columns + `rank_by`; rename "Market"→"Yahoo Fundamentals"); (2) Phase-2 backend hook = `finance_source` param on `compute_tool_b_in_memory` + `screening_verdict_official` + provenance/components on `_MappedField` (matched to the code's real branches); (3) build the unified metric object alongside the flat columns; (4) roll to detail snapshot → candidate finder → Tool D via the shared recompute; (5) historical fundamentals as a **separate** artifact with `period_type` first. Fix the suspected Tool D empty-fundamentals bug independently. The two plans can run in parallel with the `detail_panels.py` ownership split + shared URL helper.
