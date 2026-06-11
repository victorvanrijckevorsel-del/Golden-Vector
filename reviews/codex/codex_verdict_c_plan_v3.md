# Milestone C v3 Verification Verdict

Verdict: GO

The amended Milestone C section faithfully implements my recommendations in the build instructions and Decisions table. I found one stale wording contradiction in the old blast-radius prose, but the actionable C1-C5 steps and resolved decisions are clear enough that I do not consider it blocking.

## Checks

- Candidate-vs-signal horizon split: GO. C1 defines separate `candidate_horizon_policy` and `signal_horizon_policy`, with signal as an explicit 90d v1 knob. C3 and the Decisions table also say the published Signal must stay on the global signal horizon, never per-ticker most-liquid.
- Optionability core-subset rule: GO. C1 and the Decisions table explicitly replace "all selectable horizons" with configured `core_optionability_horizons` / min-coverage semantics, with v1 90/180.
- Long-form history migration: GO. C2 covers the separate `option_signal_history.parquet` store, long-form migration, backfill from old 60/90 fields, `quote_snapshot_run_id`, IV-rank filtered by signal horizon, and calm `LIMITED_HISTORY`.
- `*_60d` rename at schema bump: GO. C2 and Decision 5 require renaming during the schema bump, with no parallel old/new production columns.
- Most-liquid selector contract: GO. C3 is backend-owned, side-aware, configured-window-only, tradable-only, robust-median-based, deterministic, and reuses `aggregate_tradable_liquidity`.
- LEAPS / CF / 60d consumers: GO. LEAPS is a named 450-650 DTE band; Candidate Finder moves to `skew_residual_signal`; blast radius 4b includes the five non-web 60d consumers and requires migration or explicit freeze/retirement.

## Non-Blocking Warning

- `reviews/codex/codex_option_snapshot_fallback_plan.md:512` still says the feature/signal layer must be "generalized to long-dated expiries first." That is stale prose from the previous version and contradicts the resolved design. The actual implementation sections correctly split candidate horizons from signal horizons and keep the published signal on the explicit short/medium 90d knob. I would clean this sentence before handing C1/C2 to another implementer, but it does not change my GO verdict because C1-C5 and the Decisions table are unambiguous.
