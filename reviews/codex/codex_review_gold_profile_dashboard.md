# Review - Gold Profile Dashboard Plan

Verdict: READY WITH CHANGES

The direction is good: the profile curve and label are clearer than the current dot cloud, and computing `gold_tilt` in the Lab build is the right seam. The plan needs a tighter artifact/config contract before coding, mainly so the label cannot drift into a hidden composite or a serve-side calculation.

## Findings

### MEDIUM - Config contract is underspecified for the label thresholds

The plan says thresholds live "ONCE in config" but leaves the location vague as `tool_*`/lab config in `reviews/codex/claude_gold_profile_dashboard_plan.md:52`. Today Tool C has a validated config model and YAML in `golden_vector/contracts/config_models.py:560` and `config/tool_c.yaml:1`, but the Lab dial itself is still driven by module constants in `golden_vector/lab/conditional_dial.py:36`, `golden_vector/lab/conditional_dial.py:51`, and `golden_vector/lab/conditional_dial.py:58`. Fix: add an explicit Lab/gold-profile config contract, not another constant. Minimum fields: `tilt_threshold`, `min_usable_down_buckets`, `min_usable_up_buckets`, `down_buckets`, `up_buckets`, and `default_profile_horizon`. Validate signs/ranges, stamp those values into the Lab config hash at `golden_vector/lab/conditional_dial.py:66`, and add a test that changing a threshold makes the artifact stale rather than silently reinterpreting old labels.

### MEDIUM - "Usable bucket" must be defined exactly, not inferred

The plan says use "USABLE" buckets at `reviews/codex/claude_gold_profile_dashboard_plan.md:44`, but this needs to map to the existing cell contract: `gdx_insufficient_history == False` plus finite `p_beat_gdx_shrunk`. The builder already sets thin cells to null when `effective_n < min_effective_n` in `golden_vector/lab/conditional_dial.py:179` and exposes the GDX usable flag/columns in `golden_vector/lab/conditional_dial.py:329` through `golden_vector/lab/conditional_dial.py:338`. Fix: define the profile builder as consuming only rows where `gdx_insufficient_history` is false and `p_beat_gdx_shrunk` is non-null; persist `usable_down_bucket_count`, `usable_up_bucket_count`, and `used_buckets`. Tests should cover one-sided history, null shrunk values, and a threshold-edge case.

### MEDIUM - Current data means labels will often be based on only one down and one up bucket

I checked `data/lab/dial_cells_latest.parquet`: at the 13w horizon, 54/65 names have at least one usable down bucket and one usable up bucket, but 0/65 have both down buckets and both up buckets usable. Similar for 4w/8w; 26w has no names with both sides usable. So the proposed `>=1` floor is practical, but the UI must not imply "whole gold spectrum" when the label is really based on the usable middle buckets. Fix: keep the default floor at 1 each, but render the basis beside the label, e.g. "based on 1 down bucket and 1 up bucket at 13w." If Emanuel wants a stricter "whole-spectrum" label later, make that a config choice, not a hidden hardening.

### MEDIUM - Persist a separate `dial_profile` artifact, not columns in meta

The plan offers "a small `dial_profile_latest.parquet`, or columns on the cells meta" at `reviews/codex/claude_gold_profile_dashboard_plan.md:60`. Per-ticker/per-horizon labels do not belong in metadata. The current Lab publisher already writes run-stamped cells, episodes, and relative-strength artifacts at `golden_vector/lab/conditional_dial.py:750` through `golden_vector/lab/conditional_dial.py:763`, with artifact names in meta at `golden_vector/lab/conditional_dial.py:804`. Fix: add a fourth run-stamped artifact, e.g. `dial_profile_<run_id>.parquet` plus `dial_profile_latest.parquet`, one row per `(ticker, horizon_weeks, benchmark)`. Include `gold_tilt`, `gold_tilt_label`, `label_status`, component values, bucket counts, config version/hash, and caveat text. Add it to `run_stamped_artifacts`, latest aliases, required-column tests, and stale-schema checks.

### MEDIUM - The label must be horizon-scoped in wording and schema

The plan correctly says compute per `(ticker, horizon)` at `reviews/codex/claude_gold_profile_dashboard_plan.md:60`, but the proposed language at `reviews/codex/claude_gold_profile_dashboard_plan.md:54` reads like a permanent company identity. This can mislead because the label can change between 4w, 13w, and 26w. Fix: schema and UI should call it "13w historical tilt" or "selected-horizon tilt", and the page should never say simply "this miner is defensive" without the selected horizon, benchmark, and coverage count.

### LOW - The `gold_tilt` metric is honest, but equal-bucket weighting must be explicit

Using `p_beat_gdx_shrunk` is reasonable because it is already the ranked, shrinkage-adjusted cell number from the single backend counting path (`golden_vector/lab/conditional_dial.py:153`). Equal-weighting the usable down buckets and equal-weighting the usable up buckets is also reasonable for a scenario-profile view. It should not be replaced by episode weighting, because that would let common regimes dominate the rare extreme regimes. Fix: state in the plan and artifact metadata that `gold_tilt` is equal-weighted across usable buckets, not weighted by episode count.

### LOW - Build-side compute and serve-read seam is correct; add the guardrail test now

Computing the label in the build is correct. The current serve loader states the right boundary at `golden_vector/serve/lab_curve_data.py:13`, and there is already a no-arithmetic guardrail for Lab modules in `tests/test_lab_page.py:262`. Fix: extend that guardrail to any new profile reader/render module and forbid `.mean(`, `.groupby(`, `p_beat_gdx_shrunk` aggregation, and label words such as `Defensive`/`Pro-cyclical` being decided in serve. Serve may only choose display text from persisted `gold_tilt_label` and `label_status`.

### LOW - Add "no forced label" as a first-class status, not just empty text

The plan's refusal text at `reviews/codex/claude_gold_profile_dashboard_plan.md:49` is right, but it should be persisted as a machine-readable status. Fix: use statuses like `OK`, `INSUFFICIENT_CROSS_SCENARIO_HISTORY`, and `MISSING_COMPONENTS`, with `gold_tilt_label` null unless status is `OK`. This protects downstream screens from accidentally ranking or filtering on a placeholder label.

## Suggested Build Contract

- Add validated Lab profile config with default `tilt_threshold: 0.10`, `min_usable_down_buckets: 1`, `min_usable_up_buckets: 1`, `down_buckets: [gold_down_big, gold_down]`, `up_buckets: [gold_up, gold_up_big]`.
- Add `dial_profile_latest.parquet` and run-stamped profile artifacts.
- Build profiles from `dial_cells` after cells are computed, not from episodes.
- Persist label status, used bucket counts, component bucket values, threshold/config fields, benchmark, horizon, and caveat.
- Update the Lab stale/config hash to include profile config.
- Extend the serve no-arithmetic guardrail and add tests for threshold changes, insufficient one-sided data, and horizon-specific labels.
