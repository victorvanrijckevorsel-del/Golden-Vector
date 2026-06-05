# Review — I2 Atomic Publish + Manifest-Authoritative Readers (Gate 2)

**Reviewer:** Claude Code (Opus 4.8)
**Subject:** I2 build, commits `c09257c..HEAD` (atomic publish, immutable-pointer manifest, reader migration, parent refresh id, one full-model button, + duplication cleanup `da4d2e3`).
**Method:** read the manifest core (`app/model_state.py`) and the refresh runner myself; ran five parallel adversarial deep-dives (atomic/fault-injection, reader-migration, parent-id/button, dup-cleanup/Tool-D-spot, general bug sweep), each verifying with live probes and file:line evidence; cross-checked findings against the code directly.
**Grade: CONDITIONAL PASS.** The core I2 guarantee — atomic all-or-nothing publish — is **genuinely correct and well-tested** (this is good, careful work). But there is **one real correctness bug to fix before I3**, and **one architectural choice I'd change now** because I3 builds directly on it. Fix H1, decide on M1, and the gate is cleared.

---

## What's solid (verified, not taken on trust)
- **Atomic publish is real, not theater.** The whole build is published by a single `tmp.replace(latest_model_state.json)` *after* every stage succeeds (`cli.py:2490`, the only production caller). A failed stage returns before publish. Verified end-to-end with live probes.
- **The fault-injection test genuinely proves all-or-nothing.** `test_cli_refresh_and_status.py:361-428` injects a real mid-refresh failure (Tool C `raise`), then asserts the previous manifest is byte-unchanged **and** that readers still return the OLD coherent Tool B (`snapshot_refresh_run_id == ["refresh-old"]` while the mutable alias already shows `refresh-new`). That's the right assertion, and perturbing it breaks the test.
- **Readers in the I2 scope resolve through the manifest and fail closed.** Candidate Finder, workspace/Tool A detail, Option Trading, Tool B override, standalone `tool-c`/`tool-d`, and `status` all resolve via the manifest and return empty/raise on a corrupt (or non-object `[]`) manifest — no silent drop to a mutable alias, no double-fallback.
- **One parent refresh id**, minted once (`cli.py:2393`), threaded into the manifest and the immutable artifact stamps. ✓
- **One full-model refresh button**: the UI button now runs `python main.py refresh` (full pipeline, not options-only), background, Windows-aware detached spawn (`CREATE_NEW_PROCESS_GROUP|DETACHED_PROCESS`), with stale-lock recovery so it never sticks on "running". ✓
- **Tool D spot is well-defended (two layers):** a scenario `--gold-price` run never overwrites the spot alias, *and* the Finder blanks the quality rank if the loaded Tool D isn't a spot run. Two real tests. ✓
- **Duplication cleanup (`da4d2e3`) is behavior-preserving** for `combine_statuses` and `files` (the raise-vs-None policy is correctly preserved by import-alias).

---

## Findings

### H1 (High, correctness — fix before I3) — `refresh --skip-tool-b` produces fresh data that the whole app silently ignores
`write_current_model_state_manifest(...)` lives **inside the non-skip `else` branch** (`cli.py:2489-2495`). So `refresh --skip-tool-b` runs update-data + Tool A — writing fresh foundation/Tool A aliases **and** new run-stamped immutable files — but **never republishes the manifest**. Because every I2 reader now resolves *through* the manifest, they stay pinned to the **old** Tool A; the freshly-produced Tool A is invisible to the entire UI/CLI. Silent staleness, no error.
- It's a CLI-only path (the UI button runs full `refresh`), so impact is bounded — but it's exactly the failure mode the manifest-authoritative design introduces, and "I ran a refresh and nothing changed" is a nasty thing to debug.
- **Fix:** publish a manifest at the end of the skip path too (new Tool A + carried-forward Tool B/C/D, marked appropriately), or block `--skip-tool-b` from leaving aliases that disagree with the manifest. Add a regression test.

### M1 (Medium, architecture — the one design I'd change now) — immutability is *reconstructed by content-hashing the mutable alias*, not declared by the writer
The manifest finds each "immutable" artifact by **sha256-matching the mutable `*_latest.parquet` alias against retained `*_latest_<runid>.parquet` twins** (`model_state.py:432-490, 708-757`). The writer already knows the run-id at write time, but the manifest reverse-engineers identity by bytes. Consequences:
- **Fragile:** the alias and its run-stamped twin are written by two independent `to_parquet()` calls. They're byte-identical today (verified: pyarrow 24.0.0), but a pyarrow upgrade that embeds a timestamp/UUID in footer metadata, or a schema-arg change on one call site, breaks the match → `immutable` stays False → `_artifact_health_warnings` flags "not immutable" → **state flips to incomplete** AND `resolve_current_model_artifact_path` returns None (it hard-requires `immutable is True`) → **readers get empty frames and `tool-c` raises "No Tool A current output exists yet"** for a file that's sitting right there. A cosmetic serialization change becomes a misleading total outage.
- **Perf:** when the run-id fast-path misses, it globs and sha256-hashes *every* retained twin on every build; retained runs grow unbounded (no retention until I4), so this degrades linearly.
- **Why now:** I3 leans harder on the manifest pointing at immutable artifacts, so this is the cheapest moment to make it robust. **Fix:** have the persist/refresh layer **record the run-stamped immutable path directly** (it knows `run_context.run_id`), and have the manifest reference that — join on the run-id, not the bytes. Removes the fragility, the perf scan, and the misleading-outage failure mode in one move.

### M2 (Medium, architecture) — `build_current_model_state_manifest` is impure (a "build/inspect" function writes files)
Its docstring says "Inspect current published artifacts and return a manifest," but it calls `_snapshot_json_artifact`, which `write_bytes` + atomic-replaces immutable JSON copies into `intermediate_status_dir` on every call (`model_state.py:199-256, 682-706`). Tests that call `build_*` directly write files as a side effect. **Fix:** keep `build_*` pure (inspection only); move the snapshot materialization into `write_current_model_state_manifest`, or rename to reflect that it materializes.

### M3 (Medium) — the hedge-readiness report bypasses the manifest entirely
`hedge/report.py:952-956` reads the Tool A/Tool B mutable `*_latest` aliases directly (`_read_required_parquet`/`_read_optional_parquet`, no manifest, no fail-closed). It's outside the named I2 reader list, but it's a genuine data reader on the same aliases everything else now resolves through the manifest — so `hedge-readiness` can show Tool A/B out of alignment with the coherent build. **Fix (if it should reflect the current build):** route it through `read_current_model_parquet(paths, "tool_a"/"tool_b", ...)`.

### M4 (Medium, irony) — the same diff that adds the anti-duplication rule leaves `_unique_strings` forked 4× with *divergent* behavior
`da4d2e3`/`5a46c97` add the AGENTS.md "be ruthless about duplication … `_unique_strings` … put shared utils in `golden_vector/common/`" rule, yet four copies remain and they **disagree**: `hedge/report.py:1336` does **not** filter the literal `"nan"` while the other three do (`model_state.py:621`, `candidate_finder_data.py`, `option_trading_data.py`), and return types differ (list vs tuple). For a frame carrying a stringified `"nan"` run-id, hedge/report returns a different set than the other screens — the exact "different answer on different screens" drift the new rule warns against. Also, `model_state.py` kept its own `_clean_string`, `_mtime_iso`, `_utc_now_iso`, and a third `_alignment` (OK/WARN-only, no UNKNOWN tier) despite `common/` now existing. **Fix:** add one `unique_strings` (and the time helpers) to `common/`; fold the alignment consolidation into I5 as planned.

### CONCERNS (intended but worth knowing) — the score-eligible default flipped False→True for the UI lens
The cleanup unified `score_eligible` onto "missing/blank ⇒ **eligible**" (`common/eligibility.py`, default True). `serve/lenses.py` previously defaulted **ineligible** (whitelist). So a row whose `score_eligible` is missing/None/blank is now **scored/shown** where it used to be withheld; `model/scoring.py:99-103` flipped the same way (NaN now ranks). Production Tool A always emits a real bool, so live data is unaffected — only legacy/partial snapshots without the column change from withheld→scored. It's deliberate and locked by a test added in the same commit. Just flagging that a UI default genuinely flipped. (Bonus: `detail_panels` actually *gained* a latent-bug fix — old `bool("false")` was wrongly truthy.)

### Low (notes)
- **Manifest readers swallow read errors** (`read_current_model_parquet`/`read_current_model_json` → `except Exception: return empty/None`) — a corrupt artifact is indistinguishable from "no data." At least log it (the status renderer already has an "ERROR reading parquet" pattern to match).
- **Test-only fault hook in the production refresh path** — `_fault_after_step` + magic exit `97` + a `print` banner are interleaved through every step purely for the test. Acceptable for crash-consistency testing, but it ships test scaffolding in prod control flow; consider a cleaner seam.
- **`repo_relative` is now more tolerant** (catches `ValueError`, returns absolute) than the 3 originals that raised; harmless today, but an out-of-repo path would now silently embed an absolute path instead of failing loudly.
- **No retention** for `*_latest_*.parquet` (compounds M1's glob cost) — already slated for I4.

---

## Verdict
I2 achieves its goal: **atomic all-or-nothing publish is correct, proven, and the readers fail closed.** That's the hard part, and it's right. To clear the gate cleanly:
1. **Fix H1** (`--skip-tool-b` must not leave the manifest disagreeing with on-disk aliases) — it's a real coherence hole.
2. **Strongly recommend M1 now** (writer records the immutable run-id path; manifest joins on run-id, not bytes) — it's cheap before I3 and removes a fragile total-outage failure mode I3 would inherit.
3. M2/M3/M4 and the eligibility note are worth folding into the I5 cleanup (M4 especially — the duplication rule you just added is already being violated). Lows are notes.

After H1 (and ideally M1), **proceed to I3**.
