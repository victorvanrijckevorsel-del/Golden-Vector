# Replay Manifest Progress

Plan v2 re-grade: READY. The best-effort split, two-phase foundation capture, fixture-only implementation path, and config-list sync test address the prior R1-R5 and AF1-AF3 findings.

Baseline: `python -m pytest -q` -> 306 passed.

Step 1 (phase-1 manifest module): ready for commit in this change. Tests: 313 passed. Fixture smoke: n/a. Notes: Added writer/verifier API with no callers yet; SQLite backup explicitly closes both connections before atomic replace.

Step 2 (wire RunContext.start): ready for commit in this change. Tests: 314 passed. Fixture smoke: yes (`test_run_context_start_writes_replay_manifest`). Notes: `RunContext.start()` now writes `replay_manifest.json`; test paths copy repo configs so the hard-fail config rule is exercised without broad fixture edits.

Step 3 (foundation phase-2 capture): ready for commit in this change. Tests: 316 passed. Fixture smoke: n/a. Notes: Tool A, Tool B, and compare-horizons now patch replay manifests after loading the latest foundation snapshot; phase-2 copy failures record an error status instead of raising.

Step 4 (verify-replay CLI): ready for commit in this change. Tests: 321 passed. Fixture smoke: yes (`test_verify_replay_cli_passes_for_pristine_manifest`). Notes: Added human-readable verification output for pristine, corrupted, moved, historical pre-manifest, and missing-run cases.

Review fixes after Step 4: ready for commit in this change. Tests: 322 passed. Fixture smoke: n/a. Notes: Removed duplicate metadata write shape, made drift checks graceful without checkout context, and documented ASCII status markers as intentional for Windows-safe output.
