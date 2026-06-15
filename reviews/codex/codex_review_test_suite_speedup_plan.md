# Review - Claude Test Suite Speedup Plan

**Verdict:** READY WITH MINOR CHANGES

The direction is right: the suite is now large enough that bounded xdist parallelism is the practical lever, and the plan correctly refuses to weaken the lab leakage canaries. I verified the current tree first-hand: there is no pytest config, `requirements-dev.txt` only chains `requirements.txt` plus `ruff`, the network guard is function-scoped, `xdist` is not currently installed, and the current collected count is 1196 tests, not the plan's 1193.

## Findings

| Severity | Location | Finding | Fix |
|---|---|---|---|
| MEDIUM | `reviews/codex/claude_test_suite_speedup_plan.md:39`, `reviews/codex/claude_test_suite_speedup_plan.md:64`, `reviews/codex/claude_test_suite_speedup_plan.md:69` | The plan makes `pytest -n auto --dist loadscope` the headline command and acceptance gate before proving memory behavior. This suite is pandas/parquet heavy, and `-n auto` can be slower or unstable on a memory-constrained desktop even if `-n 4` is a large win. The plan already mentions measuring `-n 4`, but the rollout/success language still centers `auto`. | Document the default fast lane as `pytest -n 4 --dist loadscope` first, measure `-n auto` as an optional faster mode, then choose the documented default from real wall-clock + memory behavior. Keep serial `pytest` canonical. |
| MEDIUM | `reviews/codex/claude_test_suite_speedup_plan.md:47`, `tests/test_lab_validation.py:132`, `tests/test_lab_validation.py:177`, `tests/test_lab_validation.py:212`, `tests/test_lab_validation.py:323` | The module-scoped `_synthetic_panel_and_weekly()` fixture is a good speed win, but "returned read-only" is not automatic. Pandas DataFrames and dicts are mutable. Sharing the same objects across tests can create order-dependence inside `test_lab_validation.py`, even without xdist. | Build the expensive default payload once, but have the fixture return deep copies: `panel.copy(deep=True)`, `{k: v.copy(deep=True) for k, v in weekly.items()}`, and `dict(wmap)`. Do not share the exact mutable objects. |
| LOW | `reviews/codex/claude_test_suite_speedup_plan.md:12`, `reviews/codex/claude_test_suite_speedup_plan.md:68`, `reviews/codex/claude_test_suite_speedup_plan.md:89` | The test count is stale. I ran `venv\Scripts\python.exe -m pytest --collect-only -q`; the current tree collects 1196 tests. Pinning "1193 passed" in the acceptance criteria will create false failure/noise as the suite changes. | Replace exact counts with "same collected/pass count as the serial baseline from this checkout." Record the baseline in the implementation report instead of hard-coding it into the plan. |
| LOW | `reviews/codex/claude_test_suite_speedup_plan.md:31`, `reviews/codex/claude_test_suite_speedup_plan.md:32`, `tests/test_lab_curve.py:889`, `tests/test_lab_curve.py:1166`, `tests/test_lab_validation.py:310`, `tests/test_lab_validation.py:357`, `tests/test_lab_validation.py:421`, `tests/test_lab_validation.py:491` | "No shared on-disk state" and "tests are tmp-isolated" are directionally true for most tests, but overstated. A few parity/registration tests read repo-local artifacts through `ProjectPaths.discover()`, and `test_lab_curve.py` uses `tempfile.mkdtemp()` outside pytest's `tmp_path` cleanup. These are probably xdist-safe because they are read-only or unique temp dirs, but they are not the same as fully isolated per-test state. | Reword the risk section: "Most write paths are tmp-isolated; remaining repo-local tests are read-only and must stay that way." Add a quick preflight grep/check that no xdist run writes under the real `data/` or `config/` tree except intentional skipped/read-only parity checks. Prefer `tmp_path`/`tmp_path_factory` over raw `tempfile.mkdtemp()` when touching lab tests. |
| LOW | `reviews/codex/claude_test_suite_speedup_plan.md:38`, `reviews/codex/claude_test_suite_speedup_plan.md:75` | The plan says installing `pytest-xdist` needs Emanuel's approval. Under the repo's current `AGENTS.md`, installing packages listed in `requirements.txt`/dev requirements is pre-approved after the dependency is added. The approval caveat is stale and will create unnecessary interruption. | Add `pytest-xdist>=3.6` to `requirements-dev.txt`; installing/syncing dev requirements is routine. No external paid API is involved. |
| NIT | `reviews/codex/claude_test_suite_speedup_plan.md:77`, `reviews/codex/claude_test_suite_speedup_plan.md:81` | Do not add default `addopts = -n ...` in pytest config. The plan recommends opt-in, but still leaves config-default parallelism as an open rollout choice. Parallel default makes debugging with `pdb`, `-s`, and single-file investigation more annoying. | Keep bare `pytest` serial. Document `pytest -n 4 --dist loadscope` and, after measurement, optionally `pytest -n auto --dist loadscope` in `README.md`/`CLAUDE.md` or a small `scripts/test_fast.ps1`. |
| NIT | `reviews/codex/claude_test_suite_speedup_plan.md:86` | A `slow` marker is useful later but should not be bundled into this change. It is policy work and can fragment the gate if added casually. | Defer `slow` markers until after xdist is stable. If added later, every slow mark needs a rule: the full gate still runs all tests. |

## Answers To The Open Questions

1. **Default-parallel vs opt-in:** opt-in. Keep serial `pytest` canonical; document a fast xdist command.
2. **Distribution mode:** `--dist loadscope` is the right first choice. It preserves same-module behavior for the lab/config-heavy files while still parallelizing across modules.
3. **Worker count:** start with `-n 4`; measure `-n auto` and keep it only if it is faster and stable on Emanuel's machine.
4. **Dependency:** `pytest-xdist` is acceptable as a dev dependency.
5. **Hidden order-dependence:** no obvious blocker, but the plan should acknowledge repo-local read-only tests and mutable shared pandas fixtures.
6. **Slow marker:** defer.

## Verified Commands

- `venv\Scripts\python.exe -m pytest --version` -> `pytest 9.0.3`
- `venv\Scripts\python.exe -m pytest --collect-only -q` -> `1196 tests collected`
- `xdist` import check -> not installed

## Build Recommendation

Implement in this order:

1. Add `pytest-xdist>=3.6` to `requirements-dev.txt`.
2. Add the `test_lab_validation.py` cached default fixture with copy-on-return.
3. Document `pytest -n 4 --dist loadscope` as the safe fast command.
4. Run serial `pytest -q` once for baseline, then `pytest -n 4 --dist loadscope`, then `pytest -n auto --dist loadscope` once for measurement. Only run the xdist command twice if the first xdist pass is green and materially faster.

