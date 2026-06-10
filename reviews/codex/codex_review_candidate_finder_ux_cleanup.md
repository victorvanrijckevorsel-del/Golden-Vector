# Codex Review - Candidate Finder UX Cleanup

Verdict: READY WITH MINOR CHANGES

Scope reviewed: staged Candidate Finder UX/product cleanup in `config/candidate_finder.yaml`, `golden_vector/model/candidate_finder.py`, `golden_vector/contracts/config_models.py`, `golden_vector/serve/candidate_finder_data.py`, `golden_vector/serve/candidate_finder_page.py`, and related tests.

## Findings

### MEDIUM - Retired preset URLs silently become Bull

`_screen_spec_from_query()` validates the requested preset before it reaches the backend runner (`golden_vector/serve/candidate_finder_page.py:86-87`), and `_valid_preset_id()` falls back to `_DEFAULT_PRESET_ID` when the raw id is unknown (`golden_vector/serve/candidate_finder_page.py:489-494`). That means old links like `?preset=bearish_put`, `?preset=bullish_call`, or `?preset=strong_corporate_finance` now render the Bull lens with no warning. The current test locks this silent behavior by asserting `"Unknown preset ignored"` is absent (`tests/test_candidate_finder_page.py:83-88`). This is risky because the old Bearish Put link is meaningfully different from Bull. Fix: either add explicit alias handling (`bearish_put -> bear`, `bullish_call -> bull`, `strong_corporate_finance -> bull`) with a small warning, or pass the raw preset id through to `run_candidate_finder_screen()` so its existing unknown-preset warning can surface. Add one regression test for each retired id.

### MEDIUM - Tool D spot-guard field list can drift from config

The non-spot Tool D guard is the right product behavior, but the guarded fields are hardcoded in `TOOL_D_FINDER_FIELDS` (`golden_vector/serve/candidate_finder_data.py:41-49`) and blanked later by `_blank_tool_d_finder_fields()` (`golden_vector/serve/candidate_finder_data.py:842-846`). This duplicates the actual Candidate Finder config and Tool D output schema. If a future Tool D field is added to `config/candidate_finder.yaml`, it can accidentally bypass the spot-only guard and leak stressed-run values into a spot Finder screen. Fix: derive the guarded source fields from the loaded Candidate Finder config for criteria sourced from Tool D, or define a shared Tool D Finder field contract in one backend location and validate config against it. Keep the current test, but add a config-driven regression so adding a Tool D criterion without guard coverage fails.

### NIT - Debt-stress explanation hardcodes a configurable threshold

The new description for `debt_stress_gold` says `"Lower 3.0x debt line is safer."` (`config/candidate_finder.yaml:117-120`). The `3.0x` number is a Tool D config value, not an eternal label. If the danger threshold changes, this help text becomes stale. Fix: use threshold-free text such as `"Lower leverage danger line is safer."`, or render the number from the same Tool D config that owns the threshold.

## Review Questions

Product framing: Bull/Bear plus a separate Universe filter is the right simplification. It matches Emanuel's desire to stop mixing "put/call" directly into the lens name and lets the user decide whether to scan all stocks or only optionable names.

Layering: mostly clean. Descriptions live in config, the model carries them as data, and the page only renders them. I did not find ranking, gold-price, or option-candidate arithmetic added to the serve layer.

Fundamental checks: removing `fundamental_check_score` from the Candidate Finder criteria is correct. It is still available in Tool B, but it no longer appears as a vague opaque criterion in this builder.

Bull/Bear defaults: sensible first version. Bull uses direct quality/value/upside inputs. Bear uses downside beta plus fragile finance/resilience inputs. There is still some correlation between AISC, margin, FCF yield, and stress lines, but this is acceptable because weights are visible and user-controlled.

Non-spot Tool D guard: conceptually correct and now covers the currently added Tool D fields. The drift risk above is the main concern.

Tests: useful coverage was added for descriptions, UI text, and non-spot Tool D blanking. The weak spot is old/invalid preset behavior: the current page test pins silent fallback, which is exactly the behavior I would change.

## Verification

- `venv\Scripts\python.exe -m ruff check golden_vector tests` passed.
- `git diff --cached --check` passed.
- Focused pytest attempts including the Candidate Finder/app tests timed out at 120s in this environment before producing a result. I did not observe a failure, but I did not independently re-confirm the previously reported full-suite pass during this review.
