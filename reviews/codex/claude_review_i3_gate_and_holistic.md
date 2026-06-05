# I3 Gate + Holistic I1/I2/I3 Integration Review

**Reviewer:** Claude Code (Opus 4.8)
**Subject:** the full I3 milestone at HEAD `926e269`, reviewed as the formal gate, plus a cross-milestone integration check that I1 (manifest), I2 (atomic publish / parent-id / reader migration), and I3 (option data center) work together as one coherent system.
**Method:** first-hand read of the `926e269` integrity diff + the refresh spine; five parallel adversarial deep-dives (integrity-fix verification, end-to-end seam trace, fault-injection completeness, full-suite regression, plus my earlier file-by-file `claude_review_i3_deep.md`); full test suite executed.
**Grade: PASS — with one gate deliverable to record and one scheduled integration risk to keep visible.** This is high-quality, responsive work: Codex closed the four must-fix integrity findings from my deep review with corruption-exercising tests, and the three milestones integrate cleanly end-to-end.

---

## Part A — I3 gate

### A.1 The deep-review findings are genuinely closed (verified first-hand in `926e269`)
| ID | Was | Now | Evidence |
|----|-----|-----|----------|
| **F1** atomic immutable write | `to_parquet` in place | **FIXED** — `persist._write_parquet` → `write_parquet_atomic` → `atomic_write_file` (tmp + `os.replace`); the run-stamped immutable artifact goes through it | `common/parquet.py:34-40`, `common/files.py:75-85`, `persist.py:350` |
| **F2** `complete` ignored options | not required | **FIXED** — `REQUIRED_OPTION_ARTIFACT_NAMES` (slots, overview, finder_inputs) added to `REQUIRED_ARTIFACTS` + `required_for_complete=True`; a **zero-row** required option artifact now forces `state: incomplete` | `contracts/option_artifacts.py:21-25`, `model_state.py:47/343/668-689`; tests `test_model_state_manifest_requires_core_option_artifacts`, `..._rejects_empty_core_option_artifact` |
| **F3** corrupt chain swallowed at build | `read_optional_parquet` → empty, PASS | **FIXED** — `load_options_chains`/`load_options_features` now verify the manifest sha256 and use `read_required_parquet` (raises) → build FAILs → manifest not published | `option_artifact_sources.py:80-118`; test `test_run_option_artifacts_fails_on_corrupt_manifest_chain_snapshot` |
| **F4** corrupt artifact swallowed at read | swallowed → empty UI | **FIXED** — `_read_option_artifact_frames` verifies each artifact's sha256 vs the manifest and uses `read_required_parquet`; `load_option_trading_data` catches `(OSError, ValueError)` → visible "sha256 mismatch" reason | `serve/option_trading_data.py:457-488`; test `test_load_option_trading_data_surfaces_corrupt_manifest_artifact` |
| **F7** inline ticker normalize | re-grown copy | **FIXED** — replaced with shared `common/strings.normalize_ticker` across the option source/serve paths | `option_artifact_sources.py`, `option_trading_data.py` |
| **F8** wasted reads before manifest check | tool reads before `None` check | **FIXED** — `if manifest is None: return None` moved above the tool reads | `option_artifact_sources.py:42-43` |

These are closed with **corruption-exercising** tests (they tamper a file/hash and assert the failure), not mere absence tests — the right kind of proof. No new bug was introduced by the hardening (verified: the checked reads can't false-positive because the manifest hashes the same immutable bytes the resolver returns; the dropped `if frame.empty: continue` is safe because options-phase writes a manifest record and a ≥1-row feature file together 1:1).

### A.2 Still open (low — fold into I4/I5, not gate blockers)
- **F5** — `df.attrs` do not survive a parquet round-trip, so the `.attrs` stamping (`option_artifact_frames.py:312-316`) and attrs-first reads (`option_trading_data.py:503`, `model_state.py:471`) are **dead after disk I/O**. Harmless (columns carry the data), but it's misleading dead code — remove it or stop reading attrs.
- **F6** — chains are scanned ~3× per refresh (candidate slots, liquidity, contract metrics). Build-time only; consolidate to one scan feeding all three when convenient.
- **F10** — `candidate_finder_inputs` copies the whole `options_features` schema + 2 booleans; column set unpinned. Belongs to the I4 schema-contract work.

### A.3 The core gate criteria
- **Parity proof:** real and strong — `test_option_artifact_reader_matches_shared_builder_for_same_sources` runs the extracted-original builder vs the persisted-artifact reader on identical inputs and asserts equality of tickers, slots, `liquidity_tier`, usable==tradable set, liquidity measurements, overview rows, and proxy fallbacks (GDX/GDXJ), with the risk-free rate pinned equal. Not weakened. ✓
- **No raw-chain scans in serve:** confirmed — the scanner block is deleted; `scan_option_chain`/`build_bucket_slots` survive only in UI hint-text strings. ✓
- **Atomic all-or-nothing:** option-artifacts is Step 6, before the single `os.replace` manifest swap; the 6 frames are written as pre-switch staging, so no partial option set can be published; a failure aborts before publish. ✓
- **Full suite:** **731 passed, 0 failed, 0 skipped, 0 xfail.** I had an agent audit every modified existing test for weakened/deleted assertions: the ~6 changed assertions all track deliberate I2/I3 design changes (readers now trust the immutable, sha256-pinned, manifest-addressed artifacts instead of mutable aliases) — **none mask a regression**, no tests deleted. ✓

### A.4 The one gate deliverable to record
**The cold-load before/after timing number is not in the progress log.** The doc records per-stage *refresh* timings, but the plan's I3 acceptance also asks for the *page* cold-load measurement (the ~20s → fast proof). The speedup is structurally guaranteed (no raw-chain scans; the page reads 6 small parquets), but the actual number should be captured to close the gate cleanly. **Ask Codex for the `/option-trading` cold-load before vs after.**

---

## Part B — Holistic I1 + I2 + I3 integration

I traced one full `refresh` end-to-end and all readers. **The three milestones integrate as one coherent system**, with the model-state manifest as a single atomic publish gate that option artifacts join as first-class members.

### Seams that PASS
- **Seam 2 — uniform immutable resolution:** tool artifacts and all 6 option artifacts resolve through the **same** `_resolve_run_stamped_parquet` mechanism (`{prefix}_latest_{run_id}.parquet` derived from `source_run_id`); `_tool_latest_directory_and_prefix` handles tools and options via `OPTION_ARTIFACT_PREFIXES`. No parallel resolution path. ✓
- **Seam 4 — uniform fail-closed:** every reader (option UI, finder, status, standalone tools, hedge report) routes through the one resolver; a corrupt manifest (`manifest_readable: False`) returns `None` with **no** alias fallback, identically for tools and options. The `fallback_path` is honored only pre-first-publish. ✓
- **Seam 5 — build-vs-publish consistency:** during refresh the option builder reads `use_model_state=False` (fresh aliases just written by Steps 2-3), and the manifest later snapshots those **same** aliases to their immutable twins. Sequential single process → no divergence window. ✓
- **Seam 6 — coherent cache invalidation:** both `option_trading_data` and `candidate_finder_data` key their in-process caches on the model-state manifest sha256, which changes on every publish — so one publish invalidates everything coherently. ✓

### Seam 7 — CONCERNS — the single biggest integration risk (already scheduled for I5)
There are now **four** independent freshness/alignment implementations that can give **different answers on different screens for the same build**:
- `model_state._alignment` (manifest) — anchors tools to `foundation_id`, option artifacts to `options_id`.
- `option_artifact_builder._context_warnings` (option page) — anchors tool_a/tool_b to the **options** id, ignores tool_c/d.
- `candidate_finder_data._alignment` — requires all five (a/b/c/d/options) equal, plus a manual-store freshness check the others lack.
- `hedge/report._context_alignment` — a fourth near-duplicate.

Concrete divergence: rerun `tool-c` standalone after a refresh → the option page shows no warning, the Candidate Finder flags "Mixed refreshes," and CLI status shows a Tool C mismatch — same build, three verdicts. Each is locally "right" for its own dependency, but **the manifest's own `_alignment` block — purpose-built in I1/I2 to be the single source of truth — is not consumed by the option page or the finder; they recompute their own.** This is the duplication-of-logic-becomes-divergent-bug pattern from my duplication and I2 reviews, now at 4 copies. **It is correctly slated for I5 ("consolidate freshness/alignment").** The fix: have all readers consume `manifest.alignment.status/warnings` instead of recomputing — collapses 4 paths into 1 and guarantees one freshness answer per build. Keep this visible; it's the highest-value cleanup remaining.

### Seam 1 — CONCERNS (minor, provenance) — `parent_refresh_id` is decorative below the top level
The parent id is on the manifest top-level and stamped as a parquet **column** on option frames, but the per-artifact manifest **entries** (tools and options) carry only `snapshot_refresh_run_id`, not `parent_refresh_id`. So from the manifest's `artifacts` block you can confirm artifacts share the foundation/options snapshot id, but not that they belong to the same *parent refresh*. Internally consistent (snapshot id is the real alignment key), but the parent id promises more provenance than it delivers. Consider stamping it into each artifact entry in I5.

### Seam 3 — CONCERNS (minor) — `state: complete` is advisory
Coherence is enforced at the **per-artifact** level (`usable`/`immutable` in the resolver), which is the right place. But no reader blocks on the aggregate `state`, so a `complete` manifest with a stale **optional** artifact (e.g. `option_selected_candidates`) would still be served. Acceptable — just know the aggregate flag is informational, not a gate.

### Fault-injection test gaps (coverage, not correctness)
The abort-before-publish guarantee holds for all 6 stages **by code structure** (every early `return` precedes the single publish). But only **tool-b** and **option-artifacts** have real fault-injection tests that drive a mid-refresh failure and assert the previous manifest survives. **tool-a, tool-c, and especially tool-d have no failure test.** Also, the silent-empty-option case is proven only at the manifest unit level, not end-to-end through `run_refresh`. Recommend adding a tool-d fault test and an end-to-end "empty option build → manifest publishes `incomplete`" test.

---

## Verdict
**I3 passes the gate, and I1/I2/I3 integrate cleanly.** The must-fix integrity findings (F1-F4) are genuinely closed with the right kind of tests; the atomic publish, parity proof, and fail-closed reads all hold; 731/731 green with no weakened assertions. To close fully: **(1) record the cold-load before/after timing** (the one missing gate deliverable). To carry forward into I4/I5: **(2) consolidate the four alignment implementations onto the manifest's `_alignment`** (Seam 7 — the biggest remaining integration risk), **(3) add the tool-d + empty-option fault tests**, and **(4)** mop up F5/F6/F10 and the minor provenance items (Seams 1/3). None of (2)-(4) blocks proceeding.

**Recommended next:** approve I3, ask Codex for the cold-load number, then run a full `refresh` on the real machine to rebuild the local estate onto this coherent, fast build — the first time the payoff is visible.
