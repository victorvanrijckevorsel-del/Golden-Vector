# Early Review — I3 Options Data Center (interim, pre-gate)

**Reviewer:** Claude Code (Opus 4.8)
**Subject:** I3 committed work, range `eda8fb6..HEAD` (artifact contract, shared builder, persistence, refresh integration, serve flip, tests). Codex is still finishing (cold-load timing + self-review), so this is an **interim** review of the committed substance, run in parallel to save time.
**Method:** read the contract + builder myself; four parallel adversarial deep-dives (persistence/immutable mechanism, serve-flip/no-raw-scan, parity-test quality, refresh-integration atomicity), each with file:line evidence and a focused test run.
**Status: ON TRACK — strong. The hard parts are done and verified.** Two fixes to fold in before the formal gate (F1, F2); the cold-load timing + self-review are the only genuinely pending pieces.

## The substance is verified solid
- **The parity proof — the thing I said I'd scrutinize most — is real (FOUND + STRONG).** `test_option_trading_data.py:424` runs the **old extracted request-time logic** and the **new persisted-artifact path** on identical inputs and asserts equality of: same tickers, same put/call slots, same `liquidity_tier`, same usable==tradable set, same liquidity measurements, same overview rows (provenance excluded). It pins the risk-free rate equal (so deltas can't diverge) and covers GDX/GDXJ + proxy fallback. This is "new == old," not a round-trip — exactly the contract I3 had to prove. ✓✓✓
- **The serve layer no longer scans raw chains.** The heavy scanner block is deleted from `serve/option_trading_data.py`; the page reads the 6 persisted artifacts through the manifest (`resolve_current_model_artifact_path`), fail-closed on a corrupt manifest, with `raw_options_by_ticker={}` always empty. Grep finds `scan_option_chain`/`build_bucket_slots` only in UI hint-text strings, not executable paths. The Candidate Finder reads the persisted `candidate_finder_inputs` artifact and the tradable-gate is preserved. The sizing calculator works off the persisted candidate, no chain re-scan. ✓✓ (this is the ~20s-load fix, structurally achieved)
- **One engine, not two.** The builder *calls* the existing `build_bucket_slots`/`scan_option_chain`/`build_option_trading_overview` (extracted verbatim into `hedge/option_artifact_builder.py`, a non-serve module both paths import) — no parallel option-selection logic, no new `_unique_strings`. ✓
- **M1 is resolved.** My I2 review flagged the fragile sha256-reconstruction of immutability. As of `eda8fb6` that's **gone** — `_is_matching_immutable_parquet` no longer exists; immutability is now derived from the `source_run_id` (`{name}_latest_{run_id}.parquet`), a deterministic, race-free path. The new option artifacts use this same robust mechanism. ✓
- **Refresh integration is atomic all-or-nothing.** Option-artifacts is Step 6, after Tool D, **before** the manifest publish; a build failure aborts before publish and leaves the prior build intact (tested, `test_cli_refresh_and_status.py:446`); it reuses local inputs with **zero network calls**; `--skip-tool-b` correctly publishes `incomplete`. ✓
- **Round-trip is lossless** for the load-bearing fields (`liquidity_tier`, signed `delta`, `option_type` P/C, strike, expiration, horizons), schema_version + sha256 stamped. ✓

## Two fixes to fold in before the formal gate

### F1 (Medium) — the immutable option-artifact writes are NOT atomic
`persist_option_artifacts.py` writes the run-stamped immutable file (and alias) via `persist._write_parquet` → `frame.to_parquet(path)` **in place** (`persist.py:349-352`), not through the `atomic_write_bytes` helper that already exists. A crash mid-write leaves a torn parquet at the *canonical immutable path* — the one place a torn write is unacceptable, since the manifest will point readers straight at it. (It's a pre-existing pattern across `persist.py`, but the immutable artifact is exactly where it matters.) **Fix:** route the run-stamped immutable write through the atomic temp→replace helper.

### F2 (Medium) — `state: complete` does NOT require the option artifacts to be usable
The 6 option artifacts are registered `required_for_complete=False` (in `PLANNED_I3_ARTIFACTS`, not `REQUIRED_ARTIFACTS`), and no health check covers them. So a *failed* build aborts (good), but a build that returns exit 0 with **silently empty/partial** option frames still publishes as `state: complete` — and the UI then has nothing to show under a "complete" banner. For a milestone whose whole point is the option data, "complete" should guarantee the option artifacts are present and usable. **Fix:** promote the core option artifacts (at least `option_candidate_slots`, `option_trading_overview`, `candidate_finder_inputs`) into the completeness contract, or add a required-health check that flips `state` to incomplete when they're missing/zero-row. (Some artifacts can legitimately be empty — e.g. no benchmark ETFs — so a targeted check beats blanket-requiring all six.)

### F3 (Low, belt-and-suspenders) — parity coverage breadth
The parity proof is strong but runs on one fixture, and the Candidate-Finder-side column derivation is only covered transitively (its upstream slots are parity-proven, but there's no finder-side before/after assertion). Optional: add a `no_price`/empty-chain fixture to the parity test and one finder-side parity assertion.

## What's genuinely still pending (for the formal gate)
- The **cold-load timing** before/after measurement (the plan's acceptance — record the speedup).
- Codex's **duplication self-review** + the I3 gate report.

## Verdict
Starting early was worth it: the four things that decide I3 — **no raw-chain scans, a real before/after parity proof, atomic refresh integration, and the robust immutable mechanism (M1)** — are all done and verified. Fold in **F1** (atomic immutable write) and **F2** (option artifacts gate "complete"), add the cold-load timing, and this passes the gate cleanly. This is high-quality, disciplined work — the parity test in particular is exactly what I'd have demanded.
