# v2 Gold-Tilt Label — adversarial review record + fixes

**Author:** Claude · **Date:** 2026-06-14 · **Branch:** `dev-vic`
**Method:** 4-lens adversarial Workflow (math · contract-fidelity · architecture/one-copy ·
test-quality), each HIGH/MED finding then independently verified with a concrete trigger
(default-refuted). All four lenses: **APPROVE_WITH_CHANGES**.

## Confirmed findings (all fixed)

| # | Sev | Finding | Fix |
|---|-----|---------|-----|
| M1 | MED | Serve rendered the label's coverage from the *structural* bucket count (DEFAULT_BUCKETS-derived), not the *tilt-partition* count the build averaged over; editing `down_buckets`/`up_buckets` in the YAML would desync the stated basis from the real tilt. | The OK-label basis now renders the **persisted** `usable_down/up_bucket_count` (`profile_basis_down/up` on `LabCurveData`). Structural counts kept only for the chart's slope wording, with a comment distinguishing the two. |
| M2 | MED | `GoldProfileConfig` accepted non-existent bucket names (typo → silently dropped from the tilt mean + floor count, reducing evidence or flipping a label with no error). | Added `GOLD_BUCKET_NAMES` (contracts layer) + a `buckets_are_known` validator that fails loud on an unknown name. A test pins `GOLD_BUCKET_NAMES == BUCKET_LABELS` so they can't drift. |
| M3 | MED | A corrupt / column-short `dial_profile` parquet silently degraded the label to UNAVAILABLE; the §8b.4 "required-column + stale-schema" serve test was missing. | Kept the deliberate degrade (the label is optional enrichment, not load-bearing) and added serve-side tests (corrupt bytes + column-short → UNAVAILABLE, chart still renders). |
| M4 | MED | No test invoked `build_and_save`, so the profile artifact's manifest wiring (run_stamped_artifacts / latest_aliases / profile_rows) was unguarded — a dropped write would pass CI silently. | Added `test_real_build_meta_registers_profile_artifact`: asserts the REAL rebuilt meta + parquet wiring; active after a build, skips in a dataless env. (A synthetic full build needs a daily-price normalization fixture — disproportionate for 4 lines of symmetric wiring.) |
| M5 | MED | The build→persist→load→render round-trip only ever produced "Steady" on the parity fixture, so Defensive/Pro-cyclical were never proven through the persisted reader. | Added a DEF/PRO reader round-trip: build → parquet → `_ticker_profile_label` → assert the literal "Defensive"/"Pro-cyclical". |
| M6 | MED | No test proved the label tracks the *configured* threshold (a hardcoded-0.10 twin regression would be invisible). | Added a test passing a non-default `tilt_threshold=0.20` and asserting a 0.15 tilt flips Defensive→Steady, and the persisted threshold == 0.20. |
| L | LOW | `cell_bucket_is_usable` could raise `bool(pd.NA) is ambiguous` if a shrunk/flag column kept a pandas nullable dtype. | Made the predicate NA-safe via `pd.isna`; added a pd.NA test. |
| L | LOW | MISSING vs INSUFFICIENT status split only tested the flat-only (MISSING) case. | Added a present-but-all-insufficient → INSUFFICIENT test. |
| L | LOW | Threshold tests didn't pin the just-below edge or the "label decided on the rounded tilt" choice. | Added a 0.099→Steady + a 0.0999996→0.10→Defensive rounding-edge test. |
| L | LOW | `GoldProfileConfig` validators (esp. `default_profile_horizon`) absent from `test_config_models.py`. | Moved/added full GoldProfileConfig validation to `test_config_models.py` (repo-norm home). |
| NIT | — | `profile_tilt/down_mean/up_mean/threshold` read but never rendered (dead carried fields). | Now **rendered** as the transparent numeric derivation ("down-side beat rate X% vs up-side Y% (tilt ±Z, threshold T)"), per the plan's "label sits above the numbers it derives from". |
| NIT | — | Guardrail forbade the literal category words but didn't prove serve echoes the persisted string. | Added a behavioral test: an odd persisted label "Defensive-XYZ" renders verbatim. |

## Real-run verification (post-rebuild)
520 profile rows (one per ticker/horizon/benchmark). 330 OK (134 Defensive / 171 Steady /
25 Pro-cyclical), 190 INSUFFICIENT with null labels (correct). Meta wiring present.
**PRU 13w = +0.43 Defensive**, KGC = −0.13 Pro-cyclical, PRU vs GDXJ = +0.49 Defensive.

## Result
Full lab + config + parity + workspace + scorecard + datatables suites green; ruff clean.
