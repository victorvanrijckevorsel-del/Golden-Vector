# Review: Claude Gold Dial And Fundamentals Plan

Verdict: **NEEDS REWORK**

The direction is right: use the existing Tool B model seam, keep Tool A static, mirror Tool D's in-memory gold override, and keep UI arithmetic out of `serve/`. But the plan is not build-ready because the hardest parts are still underspecified: the dual-source fundamentals store, the Candidate Finder scenario contract, persisted-vs-live rank determinism, and Yahoo statement mapping. These are data-contract problems, not UI polish.

## First-Hand Checks

- Tool B already has the correct single compute seam: `compute_tool_b_in_memory(..., gold_price_assumption=...)` in `golden_vector/screening/pipeline.py:121`, and both Layer 1 and Layer 2 receive that same gold assumption at `golden_vector/screening/pipeline.py:235` and `golden_vector/screening/pipeline.py:242`.
- Tool D already uses the right live override pattern: `run_tool_d` resolves spot/current gold and passes it into `compute_tool_d_outputs(...)` at `golden_vector/cli.py:1444` and `golden_vector/cli.py:1480`. Inside Tool D, scenarios reuse Tool B rather than re-derive Tool B math at `golden_vector/model/tool_d.py:107`, `golden_vector/model/tool_d.py:119`, and `golden_vector/model/tool_d.py:129`.
- Measured local performance is acceptable for Phase A if designed carefully: Tool B full-universe in-memory recompute took **0.31s for 62 rows**; Candidate Finder current load took **0.53s** and screening/ranking took **0.09s**. This supports an interactive dial, but only with explicit scenario cache keys and no repeated raw statement fetching.
- Local `yfinance` exposes `income_stmt`, `balance_sheet`, and `cashflow` attributes, but Golden Vector's `YahooClient` has no financial-statement fetcher today; it only fetches price history, fast info, expirations, and option chains in `golden_vector/ingestion/yahoo_client.py:81`.

## HIGH Findings

### HIGH 1 - The dual-source fundamentals store is not safe or buildable as specified

The plan treats `fetched_fundamentals + company_inputs + source_verification` as enough for Official vs Our View, but the current store is a single mixed wide table. `COMPANY_INPUT_COLUMNS` combines operational inputs and financial statement fields in one row at `golden_vector/screening/manual_store.py:22`; the SQLite schema mirrors that exact mixed table at `golden_vector/screening/manual_store.py:515`. The current loader returns only `company_inputs`, `source_verification`, `reporting_calendar`, and `stock_notes` at `golden_vector/screening/manual_store.py:126`; there is no official-fundamentals layer, no analyst-overrides layer, and no reversible migration path for today's hand-entered values. Worse, the plan mentions a `MANUAL_OVERRIDE` status, but `upsert_source_verification` only allows `VERIFIED`, `ESTIMATED`, and `INCOMPLETE` at `golden_vector/screening/manual_store.py:280`.

**Fix before coding:** define the data model first. Add a field catalog that classifies each current field as operational-single-source or financial-dual-source. Create a versioned official/fetched table and a separate analyst override table, then migrate existing financial values into the override layer with explicit `MIGRATED_MANUAL` provenance while leaving operational facts in the existing operational table. Do not delete or reinterpret existing hand-entered values until an export/backup and round-trip migration test proves reversibility. Update `load_manual_screening_data` and `get_company_input_statuses` so missing-field confidence is computed from the resolved backend view, not directly from the old mixed table.

### HIGH 2 - Candidate Finder cannot safely use dial-driven Tool B/Tool D frames under the current contract

Candidate Finder currently reads persisted current artifacts through `load_candidate_finder_data` at `golden_vector/serve/candidate_finder_data.py:104`. Its cache key is based on artifact paths and model state only at `golden_vector/serve/candidate_finder_data.py:142`; it has no `gold_price`, `data_source`, or rank-mode dimension. Tool D is deliberately forced to spot: `_tool_d_finder_source_path` prefers `tool_d_spot` at `golden_vector/serve/candidate_finder_data.py:792`, and `_spot_tool_d_source` blanks quality fields when `gold_price_used != spot_gold_usd` at `golden_vector/serve/candidate_finder_data.py:806`. Existing tests pin this behavior in `tests/test_candidate_finder_data.py:319`. The completion plan also explicitly says Finder v1 should keep using persisted spot Tool D unless a new contract is designed in `reviews/codex/claude_completion_plan_portfolio_and_tool_d.md:214`.

If the plan simply "allows non-spot runs" here, it will break the safety assumption that the default Candidate Finder is a coherent persisted spot view. It may also serve stale scenario data because the cache key cannot distinguish spot Official from non-spot Our View.

**Fix before coding:** design an explicit backend scenario contract, for example `load_candidate_finder_data(..., scenario: CandidateFinderScenario | None)`. The default path must keep strict persisted-spot behavior. The scenario path should inject in-memory Tool B and Tool D frames, include `gold_price`, `source_basis`, `rank_basis`, and model-state hash in the cache key, and surface scenario provenance in the returned metadata. Update the existing non-spot Tool D guard tests instead of deleting them.

### HIGH 3 - "Persist Tool B at spot by default" requires a real refresh-input change, not a config tweak

Today `run_tool_b` resolves gold through `screening_params.resolve_gold_price(gold_price)` at `golden_vector/cli.py:1741`, whose default order is explicit override, then `default_gold_price_assumption`, then configured scenario at `golden_vector/contracts/config_models.py:773`. The Tool B CLI load path does not request gold history from the foundation snapshot at `golden_vector/cli.py:1801`, so it cannot resolve spot gold without changing the input load. The persisted Tool B schema also has only `gold_price_assumption`; it lacks `spot_gold_usd`, `spot_gold_date`, and `gold_price_basis` in `golden_vector/screening/schema.py:41`.

**Fix before coding:** Phase A1 must explicitly load fresh foundation with `include_gold_history=True`, resolve spot using the same fresh-foundation path as the Phase 1 staleness fix, and persist `gold_price_used`, `spot_gold_usd`, `spot_gold_date`, and `gold_price_basis`. If spot is missing, fail loud or publish a visible degraded status; do not silently fall back to the old configured value. Update the Tool B stale-schema guard because existing parquets will not have these columns.

### HIGH 4 - The two axes, gold price and data source, do not have a concrete output schema

Current Tool B output is one row per ticker/as-of/gold assumption with one set of columns, built in `golden_vector/screening/pipeline.py:256` and ranked/sorted at `golden_vector/screening/pipeline.py:309`. The data contract model is also one set of fields in `golden_vector/contracts/data_models.py:247`. The plan says to compute every ratio twice for Official and Our View, and also show trailing actuals, but it does not specify whether the backend output is long-form rows, wide paired columns, separate artifacts, or a `ToolBScenarioBundle`. That ambiguity will push coalesce and pairing logic into `serve/`, or produce incompatible downstream assumptions.

There is also a product issue: some combinations are incoherent or at least need labels. A trailing-actual ratio should not change when the gold dial moves; a forward modeled estimate should. An "Our View" trailing actual is only meaningful if it is an explicit manual statement override, not if it is derived from operational assumptions.

**Fix before coding:** define the canonical backend object before UI work. My recommendation is a backend `ToolBScenarioBundle` with explicit sections: `forward_official`, `forward_our_view`, `trailing_actual`, and `resolved_display_rows`. It should carry the selected `gold_price`, `source_basis`, rank basis, all coalesced display values, and rank components. The serve layer should render the bundle only. Add tests that the same ticker at spot/non-spot changes only forward-modeled fields, not trailing actual fields.

### HIGH 5 - The Yahoo financial-statement pull is too hand-wavy for production data

Golden Vector's `YahooClient` has no statement-fetching method today; it ends at price/history/options helpers in `golden_vector/ingestion/yahoo_client.py:81`. Existing normalization is for market snapshots and quote currency/unit conversion, not financial statements: `normalize_market_snapshot` converts prices and market cap at `golden_vector/normalize/market_snapshot.py:31`, while `normalize_vendor_price_unit` only handles quote-unit tags like `GBp` at `golden_vector/normalize/price_units.py:8`. That does not solve statement currency, statement scale, fiscal period, or missing-row-name problems.

The plan's implied EBITDA/net debt mapping is not reliable enough. Yahoo row labels differ by issuer and exchange; EBITDA may be absent; debt can be split across short/long-term rows; cash equivalents may be named differently; statement values may be reported in local currency while the rest of the model expects USD-normalized fields.

**Fix before coding:** make auto-pull its own milestone. Persist raw statements first, then map through a tested canonical statement mapper with row-name aliases, currency/scale metadata, period type, and fixture coverage for at least US, Canadian, Australian, and London-listed names. Only then feed Official View. Do not let Tool B read directly from `Ticker.income_stmt`/`balance_sheet`/`cashflow` inside the model.

## MEDIUM Findings

### MEDIUM 1 - Ranking determinism is only partially reusable

Tool B's current rank is deterministic enough for one score: `rank_tool_b_outputs` groups by `as_of_date` and `gold_price_assumption`, then dense-ranks `fundamental_check_score` at `golden_vector/screening/ranking.py:18`. The pipeline then sorts by `as_of_date`, `gold_price_assumption`, `fundamental_check_rank`, and `ticker` at `golden_vector/screening/pipeline.py:313`. Candidate Finder also uses stable sort orders: top entries sort by `percentile, ticker` at `golden_vector/model/candidate_finder.py:321`, and final rows sort by eligibility, score, tally, and ticker at `golden_vector/model/candidate_finder.py:394`.

That does not automatically cover new rank modes such as EV/EBITDA, trailing actual, Official vs Our View, or non-spot gold. The plan needs explicit NA handling and tie-break rules or the dial can jitter between requests when values tie or become missing.

**Fix:** add a shared rank helper per rank basis with pinned ordering: eligible first, non-missing metric first, oriented metric value, secondary `fundamental_check_score`, then ticker. Add repeated-recompute tests proving identical order.

### MEDIUM 2 - The live recompute is feasible, but the plan needs real instrumentation and cache keys

Local measurement shows Tool B full-universe recompute is fast, roughly **0.31s**, and Candidate Finder current load plus screen is roughly **0.62s**. That supports the live dial. But the existing Tool B override path reloads current foundation and manual data on every override request at `golden_vector/serve/overview_tool_b.py:251`, then catches any exception and falls back to persisted output at `golden_vector/serve/overview_tool_b.py:282`. Candidate Finder would be heavier because it joins Tool A/B/C/D/options and computes rankings.

**Fix:** set a budget, for example less than one second locally for the full candidate scenario bundle, and log load/compute/render timings separately. Add a scenario cache keyed by model-state hash, manual-store hash, `gold_price`, source basis, and rank basis. Do not precompute fixed scenarios unless measurement proves it is needed.

### MEDIUM 3 - The existing Tool B override fallback is unsafe for a core gold dial

`_resolve_tool_b_frame` falls back to persisted Tool B if recompute fails at `golden_vector/serve/overview_tool_b.py:282`. For the current hidden-ish override tool, that is survivable because it returns an error string. For a first-class gold dial, this is dangerous: the page can show a selected non-spot gold price while the table is actually persisted spot data.

**Fix:** fail closed for dial recompute. Either render a calm "could not recompute scenario" page/section or reset the selected dial to the persisted basis. Never display a non-spot selected state with spot rows underneath.

### MEDIUM 4 - Backend-only guardrails must cover coalesce and ratio pairing, not just formulas

The existing Tool B serve page mostly renders and sorts data, which is good: `_prepare_tool_b_rows` sorts by existing columns at `golden_vector/serve/overview_tool_b.py:94`, and the table formatter mostly formats values at `golden_vector/serve/overview_tool_b.py:118`. The new plan must preserve that boundary. The risk is that Official-vs-Our View coalescing, "show both ratios", or rank-basis selection creeps into `serve/overview_tool_b.py` or Candidate Finder templates.

**Fix:** add guardrail tests scanning serve modules for Tool B financial arithmetic and coalesce logic, not just gold math. The backend should emit resolved display fields and explanation strings; serve should not compute EBITDA, net debt, P/E, EV/EBITDA, fallback basis, or "official unless missing then our-view".

### MEDIUM 5 - Source verification semantics need to change before UI promises are made

The plan wants the UI to distinguish official fetched values from our estimates and manual overrides. Today `source_verification` is a simple ticker/field/status/note table; the only valid statuses are enforced at `golden_vector/screening/manual_store.py:280`. It does not store source system, fetched timestamp, statement period, currency, scale, or layered precedence.

**Fix:** either extend `source_verification` into a real provenance table, or create a separate `fundamental_sources` table for fetched statements and overrides. Do not overload `source_verification.status` with meanings it cannot represent.

### MEDIUM 6 - Phase sequencing is too broad for one PR

Phase A is valuable and relatively bounded: spot default, Tool B gold dial, backend scenario bundle, and Candidate Finder scenario contract. Phase B is a separate data-ingestion and migration project. Combining them risks mixing a user-visible feature with irreversible store migration and unreliable external data mapping.

**Fix:** split before build:

1. Tool B spot default and provenance columns.
2. Tool B in-memory gold dial with backend `ToolBScenarioBundle`.
3. Candidate Finder scenario contract using injected in-memory Tool B/Tool D frames.
4. Fundamentals store schema/migration design and reversible migration.
5. Yahoo statement raw ingestion and canonical mapper.
6. Official vs Our View UI once the store and mapper are proven.

## NIT Findings

### NIT 1 - The plan should name the exact stale-schema failures users will see after migration

Tool B has a schema guard pattern elsewhere in the project, but the new columns will make all current Tool B parquets stale. The plan should explicitly say which pages catch this and what the calm message says. Otherwise `/`, `/tool-b`, and Candidate Finder can surface a generic 500.

### NIT 2 - Use precise labels for gold price basis

Avoid "Current gold" if the value comes from the latest persisted foundation snapshot and may be previous close. Use labels like `latest persisted gold`, `spot from current foundation snapshot`, and `custom scenario`. This matters because Tool B fundamentals are not intraday quote products.

### NIT 3 - Add a no-live-data test boundary

The plan should explicitly forbid tests from calling Yahoo financial statements live. Use raw statement fixtures and fake `YahooClient` methods, the same way option/foundation ingestion tests isolate live APIs.

## What Is Strong

- Reusing `compute_tool_b_in_memory` is the right architecture. There should be one Tool B model, not a forked gold-math path.
- Mirroring Tool D's non-persisted override pattern is correct. Scenario views should not overwrite the persisted spot artifacts.
- Keeping Tool A static under the gold dial is correct. Tool A is historical structural sensitivity, not a forward gold-price scenario model.
- The desire to compare Official and Our View is product-useful, but it needs a proper data model before UI.

## Minimum Changes Required Before Coding

1. Define the Tool B scenario output contract, including gold basis, data-source basis, rank basis, coalesced display fields, and trailing-vs-forward semantics.
2. Define the Candidate Finder scenario contract and preserve the current persisted-spot guardrail for the default path.
3. Define the dual-source fundamentals schema and reversible migration for today's mixed `company_inputs`.
4. Split Yahoo financial-statement ingestion into a separate milestone with raw artifacts, mapping fixtures, currency/scale normalization, and no live test calls.
5. Add explicit backend-only guardrails for ratio math, coalesce logic, and ranking.

Until those contracts exist, implementation would be too easy to get working on one page while breaking coherence across Tool B, Candidate Finder, Tool D, and the model-state manifest.
