# Holistic Foundation Review — I1 + I2 + I3 (is the base solid?)

**Reviewer:** Claude Code (Opus 4.8)
**Date / HEAD:** committed `47a6e74` on `dev-vic`.
**Scope:** the data-architecture spine (I1 manifest, I2 atomic publish / parent-id / reader migration, I3 option data center) — reviewed as a foundation, *including* the I4 commits that touched the base (schema validation, provenance, retention copy). **Explicitly NOT reviewed:** `golden_vector/app/run_pruning.py` and `golden_vector/ingestion/collection_resilience.py` — Codex is editing those live right now (confirmed in `git status`), so reviewing them would be reviewing a half-saved file. I4's pruning/resilience is deferred until those land.
**Method:** first-hand read of the I4 foundation diffs + the spine; four parallel adversarial deep-dives (spine integrity, alignment consolidation, all-or-nothing, suite+duplication); full suite executed (excluding the two in-flight files).

## Verdict: the base is SOLID. ✅
Every load-bearing property of the spine holds at HEAD, and the committed I4 work did **not** regress it. **737 tests pass** (0 fail / 0 skip, excluding the two in-flight files). The remaining items are **consistency/cleanliness, not correctness bugs** — the foundation you'd hate to get wrong is right.

---

## The spine, property by property (all PASS, verified first-hand)

| Property | Verdict | Evidence |
|---|---|---|
| **Atomic publish** | PASS | `write_current_model_state_manifest` still serializes once → writes a retention copy to a *different* dir → `os.replace` the single `latest_model_state.json` pointer **last** (`model_state.py:53-74`). I4's retention copy uses the identical bytes and is written *before* the pointer; a crash between them leaves a harmless orphan, never a torn pointer. |
| **Immutable resolution** | PASS | `_parquet_artifact`/`_resolve_run_stamped_parquet` still derive the immutable `{prefix}_latest_{run_id}.parquet` from `source_run_id`, **uniformly** for tools and all 6 option artifacts (`model_state.py:446-506, 786-839`). Untouched by I4. |
| **Fail-closed reads** | PASS | `resolve_current_model_artifact_path` returns `None` (no mutable-alias fallback) on a corrupt/unusable manifest (`model_state.py:77-109`); every reader honors it. I4's schema check runs *after* resolution — it adds a gate, never reopens an alias fallback. |
| **Schema validation (I4)** | PASS | Wired through the **same** I3 `read_required_parquet` primitive (now backed by a shared `validate_parquet_schema`, `common/parquet.py:28-99`) — one validator, one error shape, fails loud. The private `_read_required/optional_parquet` duplicates in `latest_data`/`report` were deleted and routed through it — good consolidation. |
| **Completeness gating** | PASS | `REQUIRED_ARTIFACTS` = foundation + options + tools + the 3 core option artifacts; `state` flips to `incomplete` on missing / zero-row / non-immutable required artifacts (`model_state.py:40-48, 218-231, 669-689`). Unchanged by I4. |
| **All-or-nothing across all stages** | PASS | `write_current_model_state_manifest` is reached only after update-data + A/B/C/D + option-artifacts all return 0 (`cli.py:2707`); every stage guard returns before it. I4 added schema validation **inside** the foundation load each tool does, so a schema-invalid artifact fails a stage *before* publish; raw-equity/FX provenance is written earlier in the same build. The all-or-nothing test file is **byte-identical** across the I4 range — no assertion weakened. |
| **No I4 regression into the base** | PASS | New provenance keys degrade gracefully on old manifests (`.get(field,"")` + skip-empty); the retention dir is bootstrapped; schema strictness is scoped to artifacts that actually carry the fields. |

---

## Remaining issues (cleanliness/consistency — none break correctness)

### 1. The four-to-six divergent freshness/alignment implementations — STILL UNRESOLVED (top item)
This is the single biggest foundation-consistency risk, flagged in the I3 holistic review, and it is **not yet fixed** — only noted in the plan for I5. There are in fact **six** independent freshness verdicts, and **no screen consumes the manifest's authoritative `_alignment`** (which is computed and persisted but read by nobody):

| # | Impl | file:line | Scope it uses |
|---|---|---|---|
| 1 | `model_state._alignment` (authoritative) | `model_state.py:596` | tools→foundation, options-artifacts→options; the only one covering tool_c/d **and** options |
| 2 | `candidate_finder_data._alignment` | `candidate_finder_data.py:535` | all five equal + manual-store freshness |
| 3 | `option_artifact_builder._context_warnings` | `option_artifact_builder.py:390` | tool_a/b vs options only (ignores tool_c/d) |
| 4 | `report._context_alignment` | `report.py:1252` | tool_a/b vs options |
| 5 | CLI `status` inline | `cli.py:~2957` | a/b/c/d vs foundation |
| 6 | `detail_panels._detail_alignment` | `detail_panels.py:~105` | single Tool-A row vs foundation |

**Live divergence (not theoretical):** rerun `tool-c` standalone after a refresh → the **option page shows no warning**, the **Candidate Finder says "Mixed refreshes,"** and **CLI status says MISMATCH** — three answers for one on-disk build. Each is locally "right" for its own data dependency, but there is no single source of truth, and the manifest's own verdict (which *would* flag it) is ignored.
- **Recommendation:** **pull this to the front of I5** (it currently sits behind cosmetic helper cleanups). The fix is to route all screens through `manifest.alignment.status/warnings`, keeping each screen's extra checks (e.g. the finder's manual-store freshness) as additive notes. **Reconcile intended scope first** — the manifest verdict is stricter (flags tool_c/d), so the option page will *start* showing warnings it currently suppresses. That reconciliation is the only reason it isn't a trivial drop-in, and the reason to do it deliberately.

### 2. Numeric coercion has no shared home — ~7-9 copies (biggest mechanical duplication)
`common/` is genuinely the single source for hashing, parquet IO, strings, status, eligibility, atomic writes — **but there is no `common/numeric.py`**, so every model module rolls its own `_optional_float`/`_numeric`/`_optional_int`: `model/pipeline.py:639`, `model/structural.py:670`, `model/tool_d.py:376`, `model/tool_c.py:374/384`, `model/candidate_finder.py:458`, `serve/format_helpers.py:251`, plus `_optional_int` variants. **I4 even added another pair** (`_event_int`/`_event_float`, `options_phase.py:516/523`). Two of the copies even diverge (pipeline/structural *raise* on bad input; the others return None). **Recommendation:** add `common/numeric.py` (`optional_float`/`optional_int` + a strict variant) and route all copies through it — fold into the I5 cleanup.

### 3. The empty-artifact schema check now *depends* on `df.attrs` surviving parquet (fragility)
In the I3 review I flagged the `df.attrs` stamping as harmless dead code (columns carry the data). I4 changed that: the schema validator's **empty-artifact** path reads `schema_version` from `frame.attrs` as a fallback when a 0-row frame has no column values (`common/parquet.py` `_schema_version`). It works on the current pyarrow (24.0.0) — but **pandas does not guarantee `.attrs` round-trips through parquet**, so a pyarrow upgrade that drops attrs persistence would make empty required option artifacts fail schema validation (→ build marked incomplete or a read error). **Recommendation:** don't rely on attrs for correctness — stamp `schema_version` in a way that survives even a 0-row frame (e.g. a tiny sidecar, or always write at least a typed schema row), or pin pyarrow and document the dependency.

### 4. Minor — inline ticker normalization (~13 sites)
`normalize_ticker_series` exists in `common/strings.py`, but ~13 sites still do `.str.upper().str.strip()` inline (one with reversed order). Cosmetic; route through the helper in I5.

---

## What I deliberately did not review
`run_pruning.py` and `collection_resilience.py` (and their tests) — Codex is editing them live. The I4 *pruning/retention* and *Yahoo-resilience* surfaces should get the full gate review (especially `prune-runs`, which deletes files) once those commits land and the tree is clean. My I4 preflight (`claude_review_i4_preflight.md`, R1 = protect all retained states' artifacts + a no-delete test) is the checklist for that.

## Bottom line
**The foundation is solid — atomic publish, immutable artifacts, fail-closed reads, all-or-nothing, and completeness all hold, with no regression from I4 and 737 green tests.** You can build on it with confidence. The work left on the base is **consistency, not correctness**: (1) consolidate the 6 freshness verdicts onto the manifest's `_alignment` — **pull this to the front of I5**, it's the one inconsistency that's user-visible; (2) give numeric coercion a `common/` home; (3) remove the empty-artifact dependency on `df.attrs`; (4) the inline ticker-normalize tidy-up. None of these block anything; (1) is the only one I'd treat as more than housekeeping.
