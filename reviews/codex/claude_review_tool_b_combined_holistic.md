# Claude holistic review — Codex commit `82707d4` (Tool B simplification + Combined removal + Finder home)

**Reviewer:** Claude Code (Opus 4.8). Method: first-hand reading of the core + **empirical verification on real data** (regenerated Tool B, triggered the stale guard, rendered the home page, inspected the output schema) + a 6-dimension breadth review workflow over all 72 files, with every load-bearing workflow finding re-verified by me (I caught and discarded one false positive).
**Scope:** 72 files, +1900/−2437 (net −537 — a real simplification). **Full suite: 783 passed, 0 failed.**
**Verdict: APPROVE.** Clean, complete, well-organized, and genuinely backend-first. Findings are minor cleanups + one pre-existing issue.

## Your three questions, answered directly

### 1. Is the logic well-organized? — Yes.
- The Tool B score (`compute_fundamental_checks`) is **derived from Layer 1's `layer1_check_statuses`**, not a re-implementation — Layer 1 owns the threshold checks; verdicts.py only adds the forward-P/E check. **No duplicated threshold logic** (this was a key risk; it's handled correctly).
- A new `screening/schema.py` is the single source of truth for the Tool B output contract (column list + the stale-artifact guard).
- The deleted Combined overview's shared helpers were extracted into a new `serve/overview_helpers.py` (`_render_provenance_warnings`, `_render_refresh_summary`, filter helpers) and reused by the tool pages — good de-duplication, not copy-paste.

### 2. Any problem with the data crunching? — No (verified empirically).
- I regenerated Tool B and inspected the output: **60 rows, zero target/invented columns, all industry-standard fundamentals populated**, and the score is fully transparent — `fundamental_check_summary` = *"7/7: Data complete PASS; AISC PASS; Margin PASS; FCF yield PASS; Reserve life PASS; Net Debt/EBITDA PASS; Forward P/E PASS."*
- Score formula correct: `100 * passed / 7`. Ranking uses the check score (dense, per-group, descending) with deterministic tie-breaks; missing scores left NA.
- The home-grown `*_to_mktcap` ratios are gone from Tool B, the config, and the finder.

### 3. Is everything in the backend (no UI/request-path crunching)? — Mostly yes, with one pre-existing exception.
- **The big win:** Tool B's ratios + score are now computed at **refresh time and persisted**; the Candidate Finder's old request-time `_add_derived_ratios` derivation is **removed** — the finder now consumes the persisted Tool B parquet. The serve layer reads persisted data; no `evaluate_layer1`/`compute_layer2` calls in `serve/`.
- **One pre-existing exception (not introduced by this commit):** `detail_panels.py:1453` recomputes a fresh OLS (`np.polyfit`) + volatility *per request* when a user views a non-canonical window on the detail page. It predates this change (it was there before `ba5045a`), but it is the one genuine instance of UI-layer data crunching. (Lens scoring in `lenses.py` is request-time too, but that's inherently interactive/by-design.)

## Verified clean
- **Combined fully removed** — module (join/pipeline/ranking/`__init__`), `persist_combined_outputs`, the manifest `REQUIRED_ARTIFACTS` entry, `CombinedOutput`/`CombinedVerdictThresholds` contracts, the page, and the `/combined` route (now 404, tested). Zero dangling references in cli/model_state/paths. `combined_hash` cleanly renamed to `config_hash`.
- **Fail-loud stale guard** (`validate_tool_b_output_schema`) is **wired into every reader** (cli, candidate-finder, option-trading, workspace_state) — I triggered it live; it names the exact stale/missing columns. A schema-contract test enforces no target/upside/best_* field can return.
- **Home page = the Candidate Finder**, defaulting to the `strong_corporate_finance` preset (matches the agreed table exactly), with the refresh button + model-state banner present.
- **AISC/leverage directions fixed** — default `low_good` (quality), with `bearish_put` explicitly overriding to `high_good`.
- Contracts/config/persist are consistent; `peer_benchmarks`/`PeerBenchmark` fully removed. Test coverage is strong (schema contract, score-from-Layer-1, home route, combined-gone).

## Findings (all non-blocking)
1. **MEDIUM — stale-schema is shown as a generic "unexpected error" 500.** When the Tool B artifact is stale, every page raises `ToolBStaleSchemaError`; the outer handler (`workspace.py:498-506`) renders *"The workspace hit an unexpected error"* (500) with the actionable message only in the detail. Catch `ToolBStaleSchemaError` specifically and show a calm "Your data is from the previous version — run `python main.py refresh`" page. **Important because right after this lands, every page shows this until a refresh runs.**
2. **OPERATIONAL — a full refresh is mandatory after this merges** (the guard correctly blocks stale Tool B everywhere until then). Make it an explicit deploy step. (Note: I ran `python main.py tool-b` during review, so the local `tool_b_latest` alias is new-schema but the published manifest still points at the old run — a full refresh resolves both.)
3. **MEDIUM — empty `golden_vector/combined/` directory remains** (only stale `__pycache__`). Delete the directory to finish the teardown.
4. **LOW (pre-existing) — request-path OLS/volatility** at `detail_panels.py:1453` for the non-canonical window. Worth moving to refresh-time persistence eventually; out of scope here.
5. **NIT — `layer2.py:75` `aisc * 0.7` approximation** (operating margin when cash_cost is missing) is undocumented — add a one-line comment so the forward-estimate assumption is transparent.
6. **NIT — `bearish_put` AISC/leverage overrides** would benefit from an inline comment noting they're intentional (fragility for put screens).
7. **NOTE — `market_cap_bucket` was removed entirely** (the plan suggested keeping it). Fine for simplicity; flag only so it's a conscious choice.
8. **Discarded false positive:** a workflow agent claimed a `combined_rank` orphan in `persist.py:366` — I verified there is none (it already sorts by `tool_a_rank`/`fundamental_check_rank`). Not a finding.

## Bottom line
This is a strong, complete migration that does exactly what you asked: simple, **industry-standard** numbers, a transparent "N of 7 checks" score (derived from existing logic, with the breakdown built in), the opaque Combined tool gone, and the heavy crunching moved to refresh-time persistence with the serve layer just reading. The only items worth doing before you rely on it: a **friendly stale page** (#1) and a **mandatory refresh after merge** (#2); the rest are tidy-ups. 783 tests green.
