# Resolutions — Codex big review of the Capture & Behaviour engine

Date: 2026-06-18
Source review: `reviews/codex/codex_review_capture_engine_big.md` (Codex; 6 first-pass dimension
agents + 3 skeptic agents; verified locally at 1401 green / ruff clean).
Acted on by: Claude. **All 16 findings fixed** + the 4 INCOMPLETE prior-fix verdicts closed.

The review confirmed my earlier holistic fixes were directionally right but found that two of them
(the source-spine staleness guard and the null-label guard) were **incomplete** — applied on the
happy path but optional/partial on the production path. Those are the most important fixes here.

## Findings → resolutions

| # | Sev | Finding | Fix | Test |
|---|-----|---------|-----|------|
| 1 | HIGH | Source-spine invariant optional on BOTH sides: build could publish from the mutable `dial_episodes_latest` alias with an empty `source_spine`; serve skipped the stale guard when the behaviour pointer was missing. | Build now **fails loud** if `dial_meta.json` or its `run_stamped_artifacts.episodes` pointer is absent (no alias fallback). Serve now treats a missing/mismatched behaviour `source_spine.episodes_artifact` as **STALE** whenever the live dial has a pointer (`live_episodes and source_episodes != live_episodes`). | `test_build_and_save_dial_meta_without_episodes_pointer_fails_loud`, `test_loader_source_spine_missing_pointer_fails_closed` (+ existing match/mismatch) |
| 2 | HIGH | A trend label could fire because peer-prior shrinkage pushed the SHRUNK delta over the threshold while the RAW delta was below it. | `_beat_label` now requires BOTH `abs(trend_delta)` AND `abs(trend_delta_raw)` ≥ threshold, and all three of (shrunk delta, raw delta, MK tau) to agree in sign. New persisted column `trend_delta_raw`. | `test_beat_label_requires_raw_delta_too` |
| 3 | HIGH | Significance used a normal two-proportion z-test at anchor counts as low as 6 (z said p≈0.046 where Fisher says 0.18). | New pure-Python `fisher_exact_p` (exact hypergeometric, stdlib `math.comb`); the trend significance is now computed on the RAW integer beat counts via Fisher exact. `two_proportion_p` kept as a general primitive. | `test_fisher_exact_p_matches_known_values`; the FDR test recalibrated for Fisher's discrete p-values |
| 4 | MED | Serve didn't validate frame schema/hash against `behavior_meta`; any readable frame with the right columns was accepted. | New `_frame_matches_meta`: every row's `behavior_config_hash` / `schema_version` must match the meta, else the frame is **STALE**. | `test_loader_frame_hash_mismatch_fails_closed` |
| 5 | MED | Alpha trend gated on the beat-anchor count, so it could fire with fewer finite-alpha observations than `min_anchors`. | New persisted `alpha_anchor_n` (finite-`alpha_simple` anchors); slope/MK now computed on the finite-alpha subset and the alpha label gates on `alpha_anchor_n`. | `test_alpha_trend_gates_on_finite_alpha_count_not_beat_anchors` |
| 6 | MED | Dial provenance recorded the normalized miner inputs only as an aggregate count/rows — not auditable at file level. | `dial_meta.input_provenance.normalized_equities` now carries a per-equity `files` manifest (`{ticker, sha256, rows}`) + an `aggregate_sha256` over the sorted set. | Verified live: 65 files + aggregate stamped |
| 7 | MED | Predictive-sounding copy ("modelled probability", "more reliably beats/outperforms", "leading indicator", "better miners to own"). | Reworded to descriptive ("shrunk historical beat rate…", "higher historical beat rate", "win-size trend (descriptive)", "historically one of the stronger miners… not a recommendation"). | `test_no_predictive_copy_in_lab_behaviour_surfaces` (source-scan guard) |
| 8 | MED | Capture card omitted the persisted effective-N basis. | Card now shows "~X independent fall episodes · ~Y rise episodes" from `down/up_effective_n` (backend-read only). | extended `test_panel_renders_capture_peer_trend_with_correct_placement` |
| 9 | MED | Trend card omitted anchor counts + the q/family-size basis of the bold label. | Card now shows "recent X% of N vs older Y% of M …" and an "FDR q=… within a family of K miners" line. | same test (asserts the anchor counts + `FDR q=` + `family of`) |
| 10 | LOW | `_load_behaviour` collapsed every frame failure to CORRUPT. | Preserves the most-actionable status (CORRUPT > STALE > MISSING > EMPTY) + names the failing artifact (`behavior_artifact`); render shows it + an EMPTY message. | `test_loader_preserves_specific_failure_status_and_artifact` + corrupt test asserts the artifact |
| 11 | LOW | Trend hint hardcoded "8-week horizon" while the header was config-driven. | Hint now renders from `curve.trend_horizon`. | `test_panel_trend_hint_uses_dynamic_horizon` (non-8 fixture) |
| 12 | LOW | Trend/alpha labels used `str(... or "-")`, so a NaN label could render literal `nan`. | New `_beh_label` guard (uses `_present`); used for both labels. | `test_panel_trend_label_nan_never_renders` |
| 13 | LOW | `_warn_cutoff_drift` was untested. | Added warn/no-warn `capsys` test + a monkeypatch test proving the build invokes it every run. | `test_warn_cutoff_drift_*`, `test_build_and_save_invokes_cutoff_drift_check` |
| 14 | LOW | Serve-arithmetic guardrail was a narrow substring ban. | Broadened the ban list (`.sum(`, `.std(`, `.var(`, `.value_counts(`, `np.mean/average/percentile/sum`, `statistics.`) with a comment that only display-counts of resolved rows are permitted. | the guardrail test itself |
| 15 | NIT | Missing/NaN handling was copied locally in the behaviour panel. | All behaviour formatters + `_row_for_keys` now use the shared `golden_vector.common.numeric.is_missing`. | covered by existing render/loader tests |
| 16 | NIT | Peer-tie test only asserted ties were equal, not the exact policy or determinism. | Pinned the exact average-rank percentile values + an order-invariance (shuffled-input) assertion. | `test_peer_percentile_exact_tie_policy_and_order_invariance` |

## Prior-fix verdicts (from §3 of the review) — now closed

- **#1 cross-artifact staleness — was INCOMPLETE → CLOSED** by findings #1 + #4 above.
- **#4 null-label guard — was INCOMPLETE (trend labels still leaked nan) → CLOSED** by #12.
- **#5 label-basis hints — was INCOMPLETE → CLOSED** by #7 + #9 (anchor counts + q/family + de-predicted copy).
- #2 (trend pinned 8w), #3 (cutoffs re-grounded + drift warning), #6 (decay descriptive) — CONFIRMED, no change needed (#13 just added the missing warning test).

## Effect on live output (honesty improved)
After rebuild (dial `…064812132672Z`), the stricter Fisher + raw-delta + alpha-finite gates cut the
confident beat-trend labels from **3 → 1** IMPROVING across the whole universe — the two dropped
labels only ever passed via the z-test's small-sample optimism. Fewer, more honest labels.

## Product challenge accepted (not a code bug)
Codex's only product challenge was the predictive wording — accepted and fixed (#7). The locked
decisions (capture vs gold, CONVEX default, 13w/8w, relative-to-universe cutoffs) stand.

Verification: full suite green, ruff clean, artifacts rebuilt coherently (F1 binding verified,
F6 provenance verified live).
