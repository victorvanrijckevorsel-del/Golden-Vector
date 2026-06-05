# Deep Review — I3 Options Data Center (file-by-file, first-hand)

**Reviewer:** Claude Code (Opus 4.8)
**Subject:** I3 committed work, `eda8fb6..HEAD`. This is a first-hand, file-by-file read of every new/changed module in the milestone — not a synthesis. Every finding below was found by reading the code directly; agent cross-checks are noted where they corroborate.
**Status:** substance is strong (parity proof real, raw-chain scans gone, immutable mechanism robust, refresh integration atomic). This review adds **6 findings beyond the earlier pass** (F3-F8, F10) plus the two already known (F1, F2), with full per-module reasoning.

---

## Findings table (severity-ordered)

| ID | Sev | Location | Issue (one line) |
|----|-----|----------|------------------|
| F1 | Med | `persist_option_artifacts.py:41-61` → `persist.py:349` | Immutable run-stamped artifact written **non-atomically** (`to_parquet` in place); a crash mid-write torn-corrupts the file the manifest points readers straight at. |
| F2 | Med | `model_state.py:_optional_i3_parquet_artifact` (+ `REQUIRED_ARTIFACTS`) | `state: complete` does **not** require option artifacts; a build with empty/missing option data still publishes "complete." |
| F3 | Med | `option_artifact_sources.py:67-79` + `common/parquet.py:17` | **Build-time:** a corrupt cached chain is swallowed → empty → that ticker silently drops out of the options artifacts, and the step still returns PASS. Compounds F2. |
| F4 | Med | `option_trading_data.py:451` | **Read-time:** a manifest-blessed-but-corrupt artifact is swallowed by `read_optional_parquet` → empty UI, no error, even though the manifest stored a sha256 that *could* detect it. |
| F5 | Low | `option_artifact_frames.py:292-296`, `option_trading_data.py:468`, `model_state.py:466-467` | `df.attrs` do **not** survive a parquet round-trip, so the `.attrs` stamping + attrs-first reads are dead after disk I/O. Harmless (columns carry the data) but misleading dead defensive code. |
| F6 | Low | `cli.py run_option_artifacts` + `option_artifact_builder.py` | Chains are scanned **~3×** per refresh (candidate slots, liquidity, contract-metrics). Build-time only (acceptable), but consolidatable — compute per-contract metrics once and reuse. |
| F7 | Low | `option_artifact_frames.py:229` | Inline ticker normalization `.astype(str).str.upper().str.strip()` re-grown — another copy of the pattern the anti-duplication rule names. |
| F8 | Low | `option_artifact_sources.py:41-54` | `tool_a`/`tool_b` are read **before** the `manifest is None` early-return → wasted reads when there's no manifest. |
| F10 | Low | `option_artifact_frames.py:217-236` | `candidate_finder_inputs` copies the **entire** `options_features` schema + 2 booleans; the column set isn't pinned, so an upstream feature-schema change silently changes this artifact (schema_version is stamped but not validated — Phase 5). |
| — | Theme | read path generally | The I3 read path is **very forgiving**: `read_optional_parquet` swallows, and `_slot_from_record`/`_candidate_from_record` silently drop malformed rows. Great for resilience, but several layers turn corruption into silent emptiness rather than a visible error (F3, F4 are instances). |

Confirmed solid (verified first-hand, not just trusted): the run-id immutable mechanism (M1), strict manifest-resolved fail-closed reads, no serve-layer chain scans, the tradable-gate, the sizing calculator path, the atomic refresh integration, and the parity test. Details per module below.

---

## `contracts/option_artifacts.py` (the contract) — clean
- 6 artifacts named; `OPTION_ARTIFACT_SCHEMA_VERSION = 1`. The key line is `option_artifact_run_stamped_path` (`:36-46`): the immutable path is **`{name}_latest_{safe_file_fragment(source_run_id)}.parquet`** — derived directly from the run id. This is the robust M1 mechanism (no sha256 reconstruction). ✓
- `_prefix` raises `ValueError` on an unknown artifact (`:49-53`) — good fail-fast. The `OPTION_ARTIFACT_PREFIXES = {name: name}` identity map is a slightly pointless indirection (prefix always equals name), but harmless.

## `hedge/option_artifact_builder.py` (the one engine) — correct, reuses existing code
- `build_option_artifact_inputs` (`:50-120`) calls the **existing** `build_bucket_slots`, `scan_option_chain`, `build_option_trading_overview`, `settings_from_config` — no second selection engine. ✓ Lives in `hedge/` (non-serve), so the refresh imports *down*, not up. ✓
- `accepted_candidate_grids` → `_unique_candidates` (`:364-378`) dedups by `(horizon_days, expiration, strike, option_type)` — the correct contract-identity dedup. ✓
- `build_option_liquidity_measurements` (`:192-295`) preserves the Benchmark-ETF/Single-stock grouping, the zero-row benchmark placeholder, and tradable/watch/no-trade counts. ✓ (covers GDX/GDXJ — my plan-review flag #5).
- `build_option_source_context` uses the shared `unique_strings` (`:347-348`) — no new `_unique_strings`. ✓
- `_current_stock_price` (`:421-434`) tries feature price → Tool B `share_price_usd` → chain underlying, first positive wins. Reasonable precedence.
- **Note (F6 root):** `build_option_liquidity_measurements` and `scan_option_contract_metrics` each independently `scan_option_chain` over every chain, and `build_option_candidate_slots` scans again via `build_bucket_slots`. Three passes. Build-time, so acceptable, but a single scan feeding all three would be cleaner.

## `hedge/option_artifact_frames.py` (serialization) — lossless, with two subtle notes
- Round-trip is **lossless for the load-bearing fields** — I traced each: `liquidity_tier`, `status`, `bucket`, slot-vs-candidate prefixing (no collision because `candidate_` prefix differs, `:247-248`), `option_type` P **and** C (`:400-404`), signed `delta`, `strike`, `expiration`, `horizon_days`, `days_to_expiry`. Tuples (`quote_flags`, `notes`) are JSON-encoded (`_serialize_value :267-270`) and parsed back (`_tuple_value :430-443`). ✓
- Malformed-row handling: `_slot_from_record`/`_candidate_from_record` return `None` when a required field is missing/invalid → the row is **silently dropped** (`:306-313, :344-353`). Fail-safe on valid data, but contributes to the "silent emptiness" theme.
- **F7:** `_candidate_finder_inputs_frame` (`:229`) normalizes tickers inline rather than via a shared helper.
- **F10:** `_candidate_finder_inputs_frame` (`:217-236`) does `base = options_features.copy()` then bolts on 2 booleans — so this artifact's schema = whatever `options_features` carries, unpinned.
- **F5:** `_stamp_frame` (`:284-296`) writes stamp values to **both** columns and `result.attrs`. Columns survive parquet; `attrs` do not. So the attrs are dead weight after disk I/O.

## `hedge/option_artifact_sources.py` (input loader) — correct, two minor issues
- `load_option_artifact_source_inputs(use_model_state=...)` (`:33-64`) — during refresh it's called with `use_model_state=False` (reads the just-written aliases; the manifest isn't published yet) and from the UI/parity path with `True` (reads through the manifest). Correct split. ✓
- **F8:** `tool_a`/`tool_b` are read (`:41-52`) before the `if manifest is None: return None` (`:53`) — wasted reads on the no-manifest path. Trivial.
- **F3:** `load_options_chains` (`:67-79`) reads each chain via `read_optional_parquet` (swallows) — a corrupt chain becomes an empty frame, so the ticker silently yields no candidates and the build still PASSes. This is the build-time half of the silent-emptiness theme.
- `load_options_features` (`:82-108`): filters feature rows to the current `refresh_run_id` and takes the last match; falls back to the last row when there's no `run_id` column. Correct selection of current-refresh features.

## `ingestion/persist_option_artifacts.py` (writer) — correct shape, **F1**
- Writes 3 files per artifact: `*_output_{runid}`, the immutable `*_latest_{runid}` (`option_artifact_run_stamped_path`), and the `*_latest` alias (`:41-61`). The `source_run_id` column equals `run_context.run_id` equals the filename run id — so the manifest's derivation finds the right immutable file. ✓
- Good defensive validation: raises if any artifact frame is missing (`:29-31`) or lacks `source_run_id` (`:36-37`).
- **F1:** all writes go through `persist._write_parquet` → `frame.to_parquet(path)` **in place** (`persist.py:349`). The immutable file is the one place a torn write is unacceptable (the manifest points readers straight at it). It should use the existing `atomic_write_bytes`. (Pre-existing pattern across `persist.py`, but it lands on the canonical immutable artifact here.)

## `serve/option_trading_data.py` (the flip) — clean, fail-closed, **F4**
- `load_option_trading_data` (`:330-420`) reads the 6 artifacts via `_read_option_artifact_frames`, then rebuilds slots/candidates/liquidity/overview from frames. `raw_options_by_ticker={}` always (`:414`) — no raw chains in the request path. ✓
- `_read_option_artifact_frames` (`:445-452`) resolves each artifact via `resolve_current_model_artifact_path(paths, name)` with **no `fallback_path`** → strictly manifest-addressed, and **any** missing artifact → returns `None` → the loader shows "run refresh first" (`:348-353`). All-or-nothing on the read side, fail-closed on a corrupt manifest. ✓
- **F4:** but the per-file read uses `read_optional_parquet(path)` (`:451`), which swallows a read error → empty frame (not None). So a manifest-blessed artifact that is corrupt on disk yields an *empty* artifact → empty UI, silently. The manifest already records a sha256 for each artifact; the read path doesn't verify it, so detectable corruption is silently shown as "no data."
- `_artifact_context_value` (`:467-475`) reads `risk_free_rate`/fallback from `frame.attrs` first, then the column. As F5 notes, attrs are gone after parquet read, so the column path is what actually runs — fine, but the attrs branch is dead.

## `cli.py run_option_artifacts` + refresh integration — atomic, no network
- `run_option_artifacts` (`~:1390-1470`): loads sources (`use_model_state=False`), builds via the shared builder, scans contract metrics, builds frames, persists. Reuses local inputs only — **no network** (Yahoo is confined to update-data Step 1). ✓
- In `run_refresh` it's **Step 6/6**, after Tool D and **before** `write_current_model_state_manifest`; a non-zero exit aborts before publish (verified by `test_refresh_option_artifact_failure_keeps_previous_manifest`). So a *failed* build can't publish. ✓ (A *silently-empty-but-PASS* build is the F2/F3 gap.)

## `app/model_state.py` I3 additions — correct wiring, **F2**
- `PLANNED_I3_ARTIFACTS = OPTION_ARTIFACT_NAMES` and `_optional_i3_parquet_artifact` (`:328-345`) registers each option artifact via `_parquet_artifact(..., required_for_complete=False)`, deriving the immutable path the same robust way as the tools. ✓
- **F2 confirmed:** because they're `required_for_complete=False` and absent from `REQUIRED_ARTIFACTS`, the completeness gate ignores them. Add a required-health check on the core three (`option_candidate_slots`, `option_trading_overview`, `candidate_finder_inputs`) so "complete" guarantees usable options.
- The `_frame_attr_strings` fallback for `source_run_id` (`:466-467`) is the F5 issue again — dead after disk round-trip, but the `source_run_id` column covers it, so derivation still works.

## `common/parquet.py`, `hedge/option_availability.py` — good consolidation
- `read_optional_parquet` is now one shared helper (good dedup) — but its swallow-all-exceptions behavior is the root of F3/F4. Worth a variant that surfaces corruption (or a sha256 check at read) for manifest-blessed artifacts.
- `has_usable_option_slots` (`option_availability.py:6-12`) is the single shared tradable-gate (`liquidity_tier == "tradable"`), used by both the finder-inputs builder and the Candidate Finder. ✓ Real de-duplication of the prior inline checks.

---

## What I'd ask for before the I3 gate
1. **F1** — atomic write for the immutable artifact (use `atomic_write_bytes`).
2. **F2** — make `state: complete` require the core option artifacts present + non-empty.
3. **F3 + F4** — at least *log/surface* a swallowed corrupt chain (build) and a swallowed corrupt artifact (read); ideally verify the manifest's recorded sha256 at read so a "complete" build can't silently show empty options. These two are the same theme (silent emptiness) and are the most important after F1/F2.
4. **F5-F8, F10** — low: drop the dead `attrs` paths or make attrs real, single-pass the build scans, use the shared ticker-normalizer, move the tool reads after the manifest check, and pin the `candidate_finder_inputs` column set (or defer to the Phase-5 schema contract).
5. The still-pending gate items: the **cold-load timing** number and Codex's duplication self-review.

The milestone is genuinely close and well-built; F1/F2 are the must-fixes, F3/F4 are the ones the lighter pass missed and are worth closing because they let a "complete" build silently show no options.
