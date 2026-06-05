# I4 Preflight — short architecture checkpoint before coding

**Reviewer:** Claude Code (Opus 4.8)
**Subject:** the I4 section (Phase 4 Collection Resilience + Phase 5 Provenance/Schema/Retention) of `codex_merged_infrastructure_remediation_plan.md`.
**Grade: READY TO CODE — with 2 refinements + 1 reuse note.** The I4 plan is solid: strong phase gates (reuse shared helpers, one schema validator, no second vendor) and good acceptance criteria (retention can't delete the active state, dry-run default, per-ticker best-effort preserved, fail-loud on schema drift). Unlike I3, I4 is *additive hardening* — lower behavior-change risk. The one genuinely dangerous piece is `prune-runs` (it deletes files), so lock these before coding it.

## R1 (the one that matters) — `prune-runs` must protect ALL retained states, not just the current one
The plan says "keep latest N full model states" **and** "always keep artifacts referenced by **current** state." Those two conflict: if you keep N manifests but only protect the *current* manifest's artifacts, prune can delete the immutable run-stamped files the **other N-1 retained manifests point at** — silently breaking them (they'd resolve to deleted files). For N kept states to be *usable*, retention must keep the artifacts referenced by **every retained manifest**, not just the latest.
- **Lock:** prune keeps the union of artifacts referenced by **all retained model-state manifests** (each manifest's `artifacts[*].path` immutable files), and deletes only files referenced by **no** retained manifest.
- **Cover the option artifacts too:** the immutable run-stamped files now live in `output_options_dir` (the 6 option artifacts) as well as the tool dirs and `data/runs/`. Prune must walk all of them.
- **Test before it ships:** build ≥N+1 states, run prune, assert (a) every retained manifest still fully resolves (no referenced file deleted), (b) only genuinely-unreferenced files are removed, (c) dry-run is the default and reports without deleting. A retention bug that deletes a referenced artifact is the single most damaging thing in the whole remediation — this test is the gate.

## R2 — schema validation reuses the I3 fail-loud path, not a third mechanism
The plan correctly says "one shared schema-validation primitive" + "stamp `schema_version`." Tie it to what I3 already built so we don't grow a parallel "bad data" style:
- Build on the **existing `schema_version`** (tools have it; options have `OPTION_ARTIFACT_SCHEMA_VERSION`) — don't invent a second versioning system.
- The validation should plug into the **`read_required_parquet` checked-read pattern from I3** (which already raises with context on missing/corrupt) — extend it to also assert required columns/dtypes/schema_version, so there's **one** read-and-validate path and **one** error shape, not a separate validator bolted beside the checked read.
- Fold in **F10** from the I3 review here: pin the `candidate_finder_inputs` column set (it currently copies the whole `options_features` schema unpinned) — it's listed in the Phase-5 schema-contract targets, so make it a real pinned contract.

## R3 (reuse note) — collection stats ride the existing manifest timings
Phase 4 adds per-symbol timing + collection stats. The plan's acceptance ("one shared status shape") is right — reinforce it: surface these through the **existing `stage_timings` / manifest** machinery (already added in I2/I3), not a new parallel stats file the UI/CLI must parse separately. One status shape, read one way.

## Everything else in I4 is good as written
Retry/backoff with **per-ticker best-effort preserved**, throttling, the optional expiry-band fetch mode, raw equity/FX hashes into the replay manifest, relabeling `verify-replay` drift — all well-scoped, all with sensible acceptance criteria. No changes needed there.

## Verdict
**Code I4 — with R1 baked into the `prune-runs` design from the first commit** (it's destructive; design it safe, don't retrofit safety), R2 tying schema validation to the I3 checked-read, and R3 keeping stats on the existing manifest. Suggested rhythm: Phase 4 (resilience, low-risk) first, then Phase 5 with `prune-runs` **last and behind a dry-run + the R1 test**. Stop at the I4 gate for review — I'll scrutinize `prune-runs` and the schema-fail-loud the way I did atomic publish.
