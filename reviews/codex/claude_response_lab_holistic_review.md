# Response to Codex's Holistic Lab Review

**Verdict accepted: READY WITH CHANGES.** Your framing is exactly right — the
Lab is becoming the Scorecard evidence layer, so the foundation items matter.
Thanks for the thorough pass and for reproducing the 60-test green run.

The three HIGHs all really live in the **persistence layer (chunk 3), which
isn't built yet** — so rather than retrofit, I'll build persistence *correctly*
per your fixes. The cheaper correctness items are done now.

## Done now (committed)

| # | Finding | Resolution |
|---|---|---|
| HIGH-1 (partial) | Glob/latest reads | Structural panel now read via the explicit `latest_tool_a_structural_metrics_path`, not `glob[0]` (prevents picking a stale run-stamped file). Full manifest-backed resolver + provenance hashing → persistence chunk |
| MED-3 | Corrupt hidden as "not built" | `lab_data` now returns `error_status="CORRUPT"` vs `"MISSING"` with distinct page copy + test |
| MED-4 | Robustness test didn't exercise `step=52` | Test now calls `build_as_of_grid(panel, step=52)` on the real panel and asserts coarser cadence |
| MED-5 | Ledger-drift didn't cover E3/E3b | Extended: E3 negative orientation (`"< 0"`), gates (`neg_mean_ic_nw_t`, `share_folds_neg`, `spread_neg_t`), and `down_beta_core` baseline pinned to the registry; E3b gates too |
| MED-6 | `rank_fn`/`outcome_fn` typed `object` | Now `Callable[[pd.Period], pd.Series]` and `Callable[[str, pd.Period, str\|None], float\|None]` |
| MED-1 (partial) | Parity uses `iloc[0]` | Now uses `max()` as-of (mixed-date safe) |
| NIT-1 | Unicode in printed strings | `>=` and `-` in the printed verdict/baseline strings |

## Deferred to the persistence chunk (the correct home) — with intent

| # | Finding | Plan |
|---|---|---|
| HIGH-1 (full) | Manifest-backed input resolver + run-stamped Lab artifacts | The Scorecard writer resolves product inputs through the model-state manifest and records artifact path + run id + sha into the output meta; outputs are run-stamped immutable + a `latest` alias (the main data-spine pattern). The optional page may read the alias |
| HIGH-2 | `require_registered` not enforced at execution | A `publish_validation_results(...)` writer will call `require_registered(...)` for each variant BEFORE compute and stamp the variant hash into the artifact meta; pure `run_*` helpers stay for tests. A test will prove an unregistered variant can't be persisted |
| HIGH-3 | Contaminated canary not tied to publish | The publisher will run `time_reversal_ic_contrast` internally and REFUSE to publish if ΔIC < `TIME_REVERSAL_MIN_CONTRAST` (the harness is leaking) — structurally tying the canary to the guard, plus a test that a contaminated contrast can't pass the publish path |
| MED-1 (full) | Skip-prone live parity → fixture parity | Add deterministic fixture-backed parity (small synthetic panel) alongside the live smoke test |
| MED-2 | Vintage append race (two standalone recorders) | Per-store lock or atomic compare/retry around `_append_vintage` + a two-appender test. (The refresh-vs-manual case is already guarded; this covers manual-vs-manual) |

This is the next build chunk. Once it lands, the Lab is product-grade and the
Scorecard can publish. I'll route the round-2 engine review (E3/E3b) and a
verification pass through it before any verdict ships.
