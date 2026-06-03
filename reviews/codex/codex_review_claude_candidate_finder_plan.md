# Review: Claude Candidate Finder Plan

Grade: NEEDS CHANGES

## Findings

### R1. Options hard filter is too coarse for a put/call finder

The plan treats options as `optionability_tier != none` and calls that a YES/NO hard filter (`reviews/codex/claude_candidate_finder_plan.md:30`, `:75`, `:87`). That is not precise enough for this product. In current code, `thin` is still considered optionable (`golden_vector/hedge/_helpers.py:9`, `:115`), and put/call usability is determined later from actual side-specific candidates (`golden_vector/hedge/option_trading.py:338`, `:345`, `:409`). A bullish/call screen could therefore include a ticker with listed options but no usable calls, and a bearish/put screen could include a ticker with only poor or rejected put candidates. This is especially risky after the AEM 50-strike issue: the finder must filter by side-aware usable candidate status, not just `optionability_tier`. At minimum, define `has_usable_put_candidate` and `has_usable_call_candidate` inputs, and make the preset lens use the correct side.

### R2. Provenance freshness needs to be a gate or visible warning, not just a cache key

The data layer says it will join Tool A, Tool B, options, manual store, and cache on a composite provenance key (`reviews/codex/claude_candidate_finder_plan.md:101`). A cache key prevents stale cache reuse, but it does not prevent a blended score from mixing snapshots from different refreshes. This matters today: Tool A/B rows carry `snapshot_refresh_run_id`, options carry manifest `refresh_run_id`, and hedge readiness already has explicit alignment logic (`golden_vector/hedge/report.py:1235`, `:1265`). Candidate Finder should reuse that idea. If sources disagree, the UI/CLI should either block the blended score or render a strong "mixed refreshes" warning before rankings. Otherwise the tool can average fresh option data with stale structural/fundamental data and make the score look cleaner than the underlying evidence.

### R3. Missing-data renormalization can still reward sparse rows

The plan renormalizes weights over criteria present for each stock and only says rows below `min_criteria_fraction` are "low-confidence and optionally sink" (`reviews/codex/claude_candidate_finder_plan.md:48`, `:81`, `:82`, `:181`). "Optionally" is too loose. A stock with one excellent value and four missing values can still score near the top because the missing weights are redistributed onto the one surviving metric. The plan should make the default behavior deterministic: require a configured minimum criteria fraction for ranking, or sort low-coverage rows below complete/adequate rows even when their raw blended score is high. The visible `scored on K of N` flag is necessary but not sufficient.

### R4. Percentile semantics are underspecified

The formula says percentiles are `0-100` and inverted if low is good (`reviews/codex/claude_candidate_finder_plan.md:78`, `:130`), but the exact ranking convention is not defined. Existing code uses pandas `rank(pct=True)` for IV percentile (`golden_vector/features/options.py:151`, `:161`), which yields `1/n * 100` for the lowest non-missing value, not 0. Direction inversion can also be implemented two different ways: rank descending, or `100 - percentile`, which changes endpoints and ties. The scoring engine needs one explicit helper contract with tests for high-good, low-good, ties, all-missing, one-value, and negative values. Otherwise View 1 and View 2 can disagree subtly.

### R5. The config file will not load unless the explicit loader list is updated

The plan adds `config/candidate_finder.yaml` and `CandidateFinderConfig` (`reviews/codex/claude_candidate_finder_plan.md:50`, `:122`, `:124`), but current config loading is not directory-discovery based. `golden_vector/app/config.py:16` has an explicit `EXPECTED_CONFIG_FILES` tuple, and `AppConfig` currently has no candidate-finder field (`golden_vector/contracts/config_models.py:651`). This is straightforward, but it must be in Batch 1 acceptance criteria and tests. Otherwise the new YAML can exist while the app silently never validates or uses it.

### R6. "Adding one criterion is a YAML edit" overpromises

The plan says the registry is config-driven so "adding one is a YAML edit" (`reviews/codex/claude_candidate_finder_plan.md:50`, `:171`). That is only true for fields already present in the joined frame. New derived metrics still need loader/scorer code; future Tool C/D fields still need optional input loading and provenance handling. Tighten the claim to: "adding a criterion whose source field already exists in the joined candidate frame is a YAML edit." This matters because otherwise future features look cheaper than they are.

## Additional Notes

The core idea is strong: a point-and-click percentile screener is a practical capstone, and building it before Tool C/D is defensible because the current Tool A/B/options outputs already support useful screens. I would keep the two-view shape: per-category top-N lists plus a blended fit score. The plan should stay descriptive, not predictive.

I would defer optional per-criterion min/max threshold filters from v1 unless Emanuel explicitly needs them before first use. The UI already has criteria, directions, weights, top-N, presets, and an options filter; threshold filters add complexity and test burden. A clean v1 with bookmarkable weighted screens is more valuable than a crowded first version.

For OD-1, I recommend default top-N = 10 and minimum criteria fraction = 0.67, with rows below that threshold shown but sorted beneath eligible rows. For OD-3, build now on existing data after the above fixes; Tool C/D can plug in later as additional fields once they exist.

