# Plan — speed up the test suite (≈22 min → ≈5–7 min)

**Author:** Claude (dev-vic)
**Date:** 2026-06-15
**Status:** PROPOSED — for Codex review before implementation
**Branch target:** `dev-vic`

---

## 1. Problem

The full suite is **1193 tests, ~22 min** (`1326.93s` measured). That's painful for the build→review→fix loop and for the merge gate. Goal: cut wall-clock dramatically **without weakening any test's assertions** (especially the lab leakage-canaries).

## 2. Diagnosis (from `pytest --durations=30`)

The time is **genuine, distributed computation** — not one fixable hotspot:

| Group | Tests | ~Total | Nature |
|---|---:|---:|---|
| `test_lab_validation.py` | 7 | ~237s | Walk-forward / leakage-canary engine on synthetic data. The 2 slowest (PIT canary 60s, Tool-C parity 49s = **108s**) build live-like reconstruction artifacts. |
| `test_lab_curve.py` | 8 | ~113s | Conditional-dial artifact builds + loaders; each builds a **different** bespoke scenario (consistency / stale / bad-metadata / missing-artifact). |
| `test_option_*` (phase, routes, carry_forward, refresh, data) | ~13 | ~150s | Build option chains / manifests / refresh flows. |
| `test_candidate_finder_data.py` | 1 | ~10s | Builds ranked parquet. |

- Top 30 tests = **~575s (43%)**; the remaining **~750s** is a long tail of ~1160 tests averaging ~0.65s each.
- **Implication:** even eliminating the entire top-30 leaves ~12.5 min. There is no single villain — the only lever that gets the suite *fast* is **parallelism**. Input-shrinking would mostly hit correctness-critical canary code and is rejected (see §6).

## 3. Environment facts (verified)

- **No pytest config exists** (`pyproject.toml`/`setup.cfg`/`pytest.ini`/`tox.ini` have no `[tool.pytest…]` / `[pytest]`). Adding config is greenfield.
- `tests/conftest.py` has exactly one fixture: an `autouse`, function-scoped network-block (monkeypatches `socket`). No shared on-disk state. Parallel-safe (re-applied per test, per worker).
- Tests are **tmp-isolated**: `tests/helpers.py::build_test_paths(root)` roots `data_dir`, `raw_dir`, `runs_dir`, … under `root` (= `tmp_path`). Lab tests write to per-test `tmp_path/"lab"`. The one "live artifact" parity test only **reads** the committed artifact (read-only → safe to share across workers).
- `pytest>=8.0.0` is pinned in `requirements.txt`. `requirements-dev.txt` currently adds only `ruff`.

## 4. Proposed approach

### A. Primary — parallelize with `pytest-xdist` (the real win)
- **New dev dependency:** add `pytest-xdist>=3.6` to `requirements-dev.txt`. (Install requires Emanuel's OK per house rules — separate from this review.)
- **Invocation:** `pytest -n auto --dist loadscope`
  - `-n auto` → one worker per logical CPU.
  - `--dist loadscope` → groups tests by **module/class** so same-file tests stay on one worker. This (a) preserves any within-file fixture reuse, (b) contains module-level caches (e.g., the config `lru_cache`) to a single worker, (c) reduces cross-worker surprises.
- **Default vs opt-in (decision — see §8):** my recommendation is **opt-in** — keep the bare `pytest` serial (clean pdb/`-s`/debugging, deterministic CI), and document `pytest -n auto --dist loadscope` for fast local runs. Optionally add a config block so it's one flag.
- **Expected:** ~22 min → **~5–7 min** (not perfectly linear — the few 30–60s tests can't be split and set the floor).

### B. Secondary — one dependency-free fixture win (small, safe)
- In `test_lab_validation.py`, several tests call the helper `_synthetic_panel_and_weekly(n_tickers=20, n_weeks=750, …)` with **identical default params**, each rebuilding the same ~20×750 panel (~20s each).
- Convert the default-param build into a **`scope="module"` fixture** returned read-only; tests that use defaults consume the shared object. Saves ~80–120s.
- **Strictly excluded:** the two recon-context tests (they build per-`tmp_path` artifacts, not the helper) and **any change to canary input sizes / seeds / window sets**. We do not trade canary power for speed.

## 5. Why not other options
- **Shrink canary inputs (n_weeks/n_tickers):** rejected — these prove no look-ahead leakage; smaller panels weaken the walk-forward grid and the statistical contrast the canaries rely on.
- **Share fixtures in `test_lab_curve.py`:** low yield — each test builds a *different* scenario, so there's little identical work to dedupe.
- **Mark slow tests / split a "fast" subset:** doesn't speed the full gate; parallelism does.

## 6. Risks & mitigations

| # | Risk | Likelihood | Mitigation |
|---|---|---|---|
| R1 | Shared on-disk state racing across workers | **Low** — tests are tmp-isolated (verified) | `--dist loadscope`; full xdist run must match the 1193-green serial baseline; investigate any new failure for a hard-coded path. |
| R2 | Module-level / `lru_cache` config state leaking between tests | Low | Separate worker processes + `loadscope` keep same-file tests together (same as serial today). |
| R3 | The `autouse` network-guard fixture under xdist | Very low | It's function-scoped/monkeypatch — re-applied per test per worker; nothing global. |
| R4 | Determinism tests (deliberate ties / NA) | None | xdist changes *which worker* runs a test, never within-test behavior. |
| R5 | Flakiness / hidden order-dependence surfaced by reordering | Low–Med | Run the full xdist suite **twice**; any test that passes serial but fails/flakes parallel is a real isolation bug to fix (not hidden by reverting to serial). |
| R6 | Memory pressure (pandas-heavy tests × N workers) | Med on low-RAM machines | If OOM/slow, cap workers (`-n 4` or `-n logical`/2) instead of `auto`; document the cap. |
| R7 | The live-artifact parity test read under parallel readers | None | Read-only; concurrent reads are safe. |

## 7. Verification plan (acceptance criteria)
1. Baseline already established: **serial = 1193 passed** (green).
2. `pytest -n auto --dist loadscope` → **must be 1193 passed**, zero new failures.
3. Run it **twice** → identical pass set, no flakiness.
4. Record wall-clock for both `-n auto` and a capped `-n 4`; pick the default we document.
5. Spot-run a single slow file serially (`pytest tests/test_lab_validation.py`) to confirm debuggability is unchanged when not using `-n`.

## 8. Rollout / commit plan
1. Add `pytest-xdist>=3.6` to `requirements-dev.txt` (install needs Emanuel's approval).
2. Add the `test_lab_validation.py` module-scoped panel fixture (Approach B).
3. (Decision) Either document the parallel command in `README`/`CLAUDE.md`, or add a `[tool.pytest.ini_options]` block — **do we want `-n auto` as a default `addopts`, or opt-in?** (recommend opt-in).
4. Commit on `dev-vic`; run the full xdist suite as the gate; fast-forward merge to `main` per the house workflow.

## 9. Open questions for Codex
1. **Default-parallel vs opt-in?** Default `addopts = -n auto --dist loadscope` makes every run fast but complicates `pdb`/`-s` and can mask order-dependence; opt-in keeps serial as the canonical/CI path. Which do you prefer for this repo?
2. **`loadscope` vs `loadfile` vs default `load`?** `loadscope` (module/class) seems safest for the config cache + within-file fixtures; any reason to prefer `loadfile` or plain `load` here?
3. **Worker count:** `-n auto` vs a fixed cap — any known memory-heavy tests (lab walk-forward, option chain builds) that argue for capping?
4. **Is `pytest-xdist` acceptable** as the one new dev dependency, or do you want a dependency-free-only path (accepting only the ~3–4 min from Approach B)?
5. **Hidden order-dependence:** are you aware of any tests that share process/global state (module caches, singletons, the config `lru_cache`) that would break under reordering and need `loadscope`/an explicit fix?
6. Should we also add a **`slow` marker** + a documented `pytest -m "not slow"` fast lane for the inner loop, independent of xdist?

## 10. Success criteria
- Full suite **green (1193)** under `-n auto --dist loadscope`, stable across two runs.
- Wall-clock **≤ ~7 min** on Emanuel's machine (vs ~22 min).
- No assertion weakened; no canary input shrunk.
- Serial `pytest` still works unchanged for debugging.
