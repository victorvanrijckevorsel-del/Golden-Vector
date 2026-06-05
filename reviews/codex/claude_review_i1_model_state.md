# Review — I1 Atomic Current-State Manifest (Gate 1)

**Reviewer:** Claude Code (Opus 4.8)
**Subject:** I1 build, commits `b9e4313..c09257c` (`golden_vector/app/model_state.py`, status/refresh/UI wiring, `model_state_banner.py`).
**Gate:** Stop 1 — design-lock review of the manifest shape before the rest of the app is wired to it.
**Grade: PASS — proceed to I2.** The manifest is correctly shaped as the single atomic pointer, the hardening Codex did is real and addresses genuine issues, and the perf trap (rebuilding per page) was avoided. One important directive to carry into I2, plus minor notes.

## Verified correct
- **Atomic publish.** `write_current_model_state_manifest` writes to `*.tmp` then `tmp.replace(target)` — a genuine single-file atomic swap (`model_state.py:59-64`). R1's "publish by replacing one pointer" is satisfied at the write level.
- **Forward-compatible shape (R1).** `parent_refresh_id` present and nullable (for I2); extensible `artifacts` map with `PLANNED_I3_ARTIFACTS` slots already stubbed (`option_*`, `candidate_finder_inputs`); `publish.atomic_pointer: true` and `latest_aliases_authoritative: false` make the intent explicit. The schema won't need reshaping when I2/I3 populate it.
- **present / readable / usable hardening is real and correct.** A corrupt required parquet/JSON stays `present: true, readable: false, usable: false` with a `read_error`, and completion depends on `usable` (`model_state.py:108-118, 315-323`). Corrupt files are no longer flattened into "missing" — good, that distinction matters for honest status.
- **Crash-safe loader.** A corrupt `latest_model_state.json` returns an explicit incomplete-state dict instead of raising (`model_state.py:74-92`), so the UI/CLI degrade rather than crash.
- **Perf trap avoided (the thing I most wanted to check).** The heavy work (sha256 every artifact + `read_parquet` every tool) lives in `build_*`, which is called **only** by `refresh` (`cli.py:2431`). The UI (`candidate_finder_data.py:183`, `workspace.py:200`, `workspace_state.py:90`) and `status` (`cli.py:2472`) call `load_*` — a cheap JSON read. So pages don't re-hash parquets. Correct.
- **Cache coherence.** The Candidate Finder cache key now includes the manifest file hash (`candidate_finder_data.py:48,142`), so the banner can't go stale behind the process cache. Good catch by Codex.
- **Honest current state.** The sample manifest correctly reports `state: incomplete` for the real local estate (Tool C/D missing, Tool A/B mismatched against foundation) — exactly the behavior we want.
- **Independent test run:** I re-ran the I1 suite (`test_model_state`, `cli_refresh_and_status`, `workspace_app`, `candidate_finder_data`, `candidate_finder_page`, `option_refresh`) → **105 passed.**

## The one directive to carry into I2 (not an I1 defect — a value change)
**The manifest currently records the MUTABLE `*_latest.parquet` alias paths** (e.g. `data/output/tool_a/tool_a_latest.parquet`) with their sha256/row_count captured at build time. For I1 (informational, readers still on legacy aliases) that's fine. But for **I2's atomic-pointer guarantee to actually hold, the manifest must reference IMMUTABLE, run-id-stamped artifact files** — which already exist as retained per-run outputs (`tool_a_latest_<runid>.parquet` / `tool_a_output_<runid>.parquet`).

Why it matters: if readers resolve *through* the manifest but the manifest points at mutable aliases, the alias can still be overwritten out from under the manifest (the torn-write problem isn't solved by atomically swapping only the manifest). The fix in I2: a new build writes new run-id files, the manifest points at *those*, and the manifest swap is the atomic switch — old immutable files stay intact, and the recorded sha256 stays valid forever. **The I1 schema already supports this (there's a `path` per artifact) — it's a value change in I2, not a reshape.** Flagging it now because this gate is where we lock the shape, and getting this right is the whole point of I2.

## Minor notes (non-blocking)
1. **Third alignment implementation.** `model_state._alignment` now joins `candidate_finder_data._alignment` and the legacy CLI alignment — three computations of the same idea. Acceptable for I1, but I2/I5 should converge everyone onto the manifest's alignment as the single source (the plan already schedules freshness-helper consolidation in I5).
2. **I1 manifest is descriptive-only — don't over-trust it yet.** Because publish isn't atomic until I2, a *failed* full refresh aborts before rewriting the manifest, so the manifest can describe a prior build while the `*_latest` aliases on disk are half-updated. That's expected (readers don't depend on it yet), but worth stating so nobody treats the I1 manifest as authoritative before I2.
3. **Tiny cosmetic:** a present-but-corrupt parquet emits both a `read_error` and a misleading `"<tool> has zero rows"` health warning (row_count defaults to 0 when the read failed). Harmless, but the zero-row check could skip artifacts that aren't `readable`.

## Verdict
**I1 passes the design-lock gate.** The manifest shape is right, forward-compatible, atomically written, honestly computed, and wired without a per-page perf cost. Proceed to **I2** with the explicit directive: **point the manifest at immutable run-id-stamped artifact files (not the mutable `*_latest` aliases), migrate readers to resolve through the manifest, and make the manifest swap the atomic publish — proven by the fault-injection test.**
