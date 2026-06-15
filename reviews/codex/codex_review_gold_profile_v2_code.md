# Gold-Profile Dashboard v2 Code Review

Verdict: APPROVE WITH CHANGES

Scope reviewed first-hand:

- `golden_vector/contracts/config_models.py`
- `config/lab_gold_profile.yaml`
- `golden_vector/lab/conditional_dial.py`
- `golden_vector/serve/lab_curve_data.py`
- `golden_vector/serve/lab_curve_page.py`
- `tests/test_lab_gold_profile.py`
- `tests/test_lab_curve.py`
- `tests/test_config_models.py`
- `tests/test_lab_page.py`

Checks run:

- `python -m pytest tests/test_lab_gold_profile.py tests/test_lab_curve.py tests/test_config_models.py tests/test_lab_page.py -q`
- Result: 182 passed in 272.62s.
- Live page check:
  - `/lab/dial/PRU?scenario=gold_down&horizon=13&benchmark=GDX` rendered `13-week historical tilt: Defensive`, tilt `+0.43`, down-side beat rate `74%`, up-side `31%`.
  - `/lab/dial/KGC?scenario=gold_down&horizon=13&benchmark=GDX` rendered `13-week historical tilt: Pro-cyclical`, tilt `-0.13`, down-side beat rate `46%`, up-side `58%`.
- Artifact check:
  - `data/lab/dial_profile_latest.parquet`: 520 rows.
  - `label_status` counts: `OK=330`, `INSUFFICIENT_CROSS_SCENARIO_HISTORY=190`.
  - PRU and KGC match Claude's claimed live examples.

## Findings

| Severity | File:line | What is wrong | Why it matters | Concrete fix |
|---|---|---|---|---|
| MED | `golden_vector/lab/conditional_dial.py:90`, `golden_vector/lab/conditional_dial.py:129`, `golden_vector/serve/lab_curve_data.py:168` | The "live config edit makes the artifact STALE" guarantee is weakened by `@lru_cache` on `default_gold_profile_config()`. `_config_is_current()` recomputes the expected hash through `dial_config_hash(...)`, but that calls the cached config unless a caller passes `profile=`. In a long-running WSGI/server process, editing `config/lab_gold_profile.yaml` can leave the old config in memory and keep the artifact looking current until process restart. | The binding contract says the profile config is stamped into the hash so threshold/bucket edits fail closed as STALE. The implementation proves that after restart, but not within the already-running local app. This is exactly the kind of stale-data failure the Lab config hash is meant to prevent. | Make the config loader either uncached or mtime-aware. A small clean fix is a `load_gold_profile_config(paths=None)` that reads YAML each time for hash checks, plus a cached wrapper only for build-time callers that explicitly want caching. Add a test that changes a temp `lab_gold_profile.yaml` in the same Python process and asserts `_artifact_is_current(meta)` flips to false without restarting. |
| MED | `tests/test_lab_curve.py:879` | The only test for `build_and_save` profile wiring is `test_real_build_meta_registers_profile_artifact`, which skips when local lab artifacts are absent (`tests/test_lab_curve.py:889`). That means a clean CI/dataless run can still pass if `build_and_save` stops writing `dial_profile_latest.parquet`, omits `run_stamped_artifacts["profile"]`, or drops `profile_rows`. | Claude's adversarial review record says M4 was fixed. It is partially fixed for this local rebuilt workspace, but not reliably guarded in CI or a clean checkout. The high-risk integration point is not the pure math helper; it is the end-to-end build wiring that writes profile artifacts and metadata. | Add a synthetic `build_and_save` integration test with temp raw gold, normalized equity, and GDX/GDXJ benchmark parquet fixtures, then assert the run-stamped profile, latest alias, `profile_rows`, `latest_aliases["profile"]`, and `run_stamped_artifacts["profile"]`. If building full fixture data is too heavy, factor the artifact/meta writer out of `build_and_save` and test that writer directly with synthetic frames. |
| LOW | `golden_vector/contracts/config_models.py:639`, `golden_vector/lab/conditional_dial.py:146`, `golden_vector/serve/workspace.py:357`, `golden_vector/serve/workspace.py:379` | `default_profile_horizon` is validated and included in the config hash, but it is not used by the Lab routes. `/lab` and `/lab/dial/...` still default to hardcoded `13` in `workspace.py`. | This is not breaking today's dashboard because the YAML value is also 13, but it is a confusing config knob: changing it invalidates artifacts while not changing the default route behavior. That is a dead config field unless it actually controls the default profile horizon. | Either wire `GoldProfileConfig.default_profile_horizon` into the `/lab` and `/lab/dial` default horizon resolution, or remove it from the config/hash until it is used. If wired, add a route/loader test proving a non-13 default changes the default selected horizon. |
| NIT | `tests/test_lab_page.py:291` | The serve guardrail forbids the category labels only as double-quoted source literals (`"Defensive"`, `"Pro-cyclical"`, `"Steady"`). A future serve-side decision could use single quotes or build strings dynamically and evade this exact token check. | The current serve code is clean: it echoes the persisted label and does not decide thresholds. This is a test-hardening issue, not a current behavior bug. But the guardrail is weaker than the review record suggests. | Use an AST-based test over string constants, or forbid bare category substrings in serve modules with an allowlist for comments/docstrings if needed. Keep the behavioral test that persists `Defensive-XYZ`; it is useful and should stay. |

## What Claude's Record Gets Right

- The tilt math is implemented as equal-bucket weighting over usable down buckets minus usable up buckets (`conditional_dial.py:818`, `conditional_dial.py:825`, `conditional_dial.py:845`).
- Threshold edges are inclusive and the label is decided on the persisted rounded tilt (`conditional_dial.py:844`, `conditional_dial.py:845`).
- `gold_tilt` and `gold_tilt_label` are null unless `label_status == OK` (`conditional_dial.py:842`, `conditional_dial.py:852`).
- One-sided or thin history does not receive a confident label.
- `cell_bucket_is_usable` is shared between build and serve for usability checks (`conditional_dial.py:746`, `lab_curve_data.py:406`).
- The OK-label coverage basis uses the persisted tilt-partition counts, not the structural chart counts (`lab_curve_data.py:369`, `lab_curve_page.py:160`).
- The renderer does not re-decide the category; it displays `curve.profile_label` from the persisted artifact (`lab_curve_page.py:157`, `lab_curve_page.py:176`).
- The page wording is horizon-scoped, benchmark-scoped, and includes the "not a prediction" caveat.
- Real artifacts match the claimed PRU/KGC examples.

## Overstatements / Caveats

- Claude's review record overstates the `build_and_save` wiring test. The real-artifact guard proves this local workspace after rebuild, but it skips in dataless environments and would not catch a dropped profile write in a clean CI run.
- The "threshold edit makes the artifact STALE" claim is true after process restart, but the current cached config loader can miss the edit inside a running process.
- The serve guardrail currently forbids double-quoted label literals, not all possible serve-side label literals. The current serve implementation is clean, but the guardrail is not quote-style complete.

No HIGH findings. I would ship this after fixing the two MED items; the actual label math and user-facing honesty are sound.
