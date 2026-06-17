# Resolutions to Codex's Phases 0–3 review

Author: Claude, 2026-06-17. Acting on `reviews/codex/codex_review_capture_behavior_engine_phases_0_3.md`
(13 findings: 4 HIGH, 7 MEDIUM, 1 LOW, 1 NIT). All adopted. Verified first-hand against the code +
rebuilt live artifacts.

| Codex finding | Sev | Resolution |
|---|---|---|
| Source-spine identity not stamped (latest-alias read) | HIGH | `build_and_save` now resolves the spine through `dial_meta.json`, reads the IMMUTABLE run-stamped episode file, and stamps `source_spine` (dial built_at, dial config_hash, dial schema, episode artifact name, rows, sha256) in `behavior_meta.json`. |
| Alpha label = raw MK p (no FDR / sign gate) | HIGH | Alpha label now BH-FDR'd within the scenario family + Theil-Sen/MK **sign-agreement** gate; persist `alpha_trend_tau`, `alpha_trend_mk_z`, `alpha_trend_q_value`. Live effect: alpha movers **121 → 1** (the 121 were multiplicity-inflated). Sensitive slope/median stay for the chart; only the badge is gated. |
| 13w cutoffs applied to all horizons | HIGH | Hard archetype emitted ONLY at `default_capture_horizon` (where the cutoffs are grounded); other horizons keep capture NUMBERS, no box. `capture_distribution` now grounds on OK (label-eligible) rows. Live: archetype-bearing horizons = [13]. |
| Hard archetype ships OK when anchors disagree | HIGH | Split: `archetype_all_rows` = raw all-rows label; display-safe `archetype` populated ONLY when `archetype_confidence == 'confirmed'` (anchors agree). Live: 47 confirmed vs 55 all-rows. |
| Beat FDR scope not stamped | MED | Stamp `trend_fdr_scope = "benchmark+horizon+gold_bucket"` + `trend_fdr_family_size` on every trend row; caveat says labels are scenario-local, not global winners. |
| Shallow config validation | MED | Validators reject `trend_window_basis != "event_time"`, non-positive floors/half-life/pool, negative EB/delta/slope. Rejection test added. |
| `STABLE` overstates | MED | Renamed `STABLE → NO_CHANGE_DETECTED` (and `ALPHA_STABLE → ALPHA_NO_CHANGE`); caveat clarifies it means "no change detected at this power", see `mde_80pct_pp`. |
| `capture_distribution` grounds on all rows | MED | Now grounds on `capture_status == 'OK'` rows (label-eligible population). |
| Zero/invalid gold denominator → OK + null | MED | A side that clears the N floor but has no finite capture → `INVALID_DOWN/UP_DENOMINATOR` status, archetype withheld. Test added. |
| Run-stamp second-precision collision | MED | Microsecond stamps in both builders + `write_run_stamped_set` fails loud if a run-stamped target already exists (immutability). |
| Capture-trend fields omitted vs plan | MED | Explicitly DEFERRED + documented in the plan (§14): capture-trend is descriptive-only, post-UI; `dial_capture` carries levels only. |
| Behaviour Parquet lacks context metadata | LOW | Added `behavior_config_hash` to `PARQUET_CONTEXT_METADATA_KEYS`; frames stamp `schema_version` + `behavior_config_hash` in Parquet metadata. Live: present. |
| `default_trend_horizon` unchecked | LOW | `build_and_save` now validates BOTH default horizons against the built set. |
| Stale archetype docstring | NIT | `compute_capture_table` docstring rewritten to the confirmed-vs-all-rows + default-horizon behavior. |

Also removed the now-unused `alpha_trend_p_threshold` config knob (alpha uses the FDR q). Tests added/updated
across `test_behavior_engine.py`, `test_behavior_trend.py`, `test_lab_statistics.py`. Full suite green.
