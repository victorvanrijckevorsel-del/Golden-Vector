# Codex Review: Tool A Phase 4 Milestone

## Scope
- Shared backbone to `tool-a` command flow
- Horizon QA to Tool A scoring handoff
- Tool A metric, label, score, and ranking logic
- Exploratory `compare-horizons` command

## Findings Fixed During Review

### P1. `tool-a` could continue into analytics after normalization QA failed
- Why it mattered:
  The project rules say no Tool A analytics should run before the USD-normalized data path has passed its gating checks. The previous CLI flow only stopped when normalization did not run at all, not when normalization ran and failed.
- Fix applied:
  [golden_vector/cli.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/cli.py) now stops `tool-a` and `compare-horizons` when normalization QA returns `FAIL`.

### P1. `tool-a` could still score after a failed horizon stage
- Why it mattered:
  Phase 4 depends on a successful Phase 3 feature layer. The prior flow still attempted Tool A scoring even when horizon QA had already failed.
- Fix applied:
  [golden_vector/cli.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/cli.py) now stops before the Tool A profile/scoring stage if horizon QA returns `FAIL`.

### P2. Stability could look artificially perfect with only one eligible horizon
- Why it mattered:
  A consistency metric is not meaningful with a single point. The previous implementation could produce a stability score of `1.0` from one eligible horizon, which would be misleading in partially covered outputs.
- Fix applied:
  [golden_vector/features/stability.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/features/stability.py) now requires at least two delta points before returning a stability score.

## Tests Added Or Updated
- [tests/test_cli_tool_a.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_cli_tool_a.py)
  - normalization-fail gate
  - horizon-fail gate
- [tests/test_stability.py](C:/Users/Emanuel/code/Golden-Vector/tests/test_stability.py)
  - minimum data requirement
  - tighter-vs-noisier dispersion behavior

## Residual Risk
- I still could not run `pytest` or the CLI in this shell because no usable Python launcher is exposed here.
- The code is statically reviewed and the test surface has been expanded, but this milestone still needs a real execution pass in the working Python environment.

## Current Verdict
- Tool A is now in a better state for external review:
  - hard gates are stricter
  - scoring rules are more internally consistent
  - review scope is well-bounded for Claude
