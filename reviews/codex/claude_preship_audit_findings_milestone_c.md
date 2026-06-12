# Pre-Ship Audit — Milestone C Findings (2026-06-12)

Audit: 6 adversarial contract verifiers on `dev-vic` at `ab48c9e` (workflow `wf_2ff1262c-f21`,
~1.25M tokens). 5/6 returned (serve-purity verifier died on a socket error during the model
switch — its surface is partially covered by the C5 guardrail test + earlier reviews; noted as a
coverage gap). Verdicts: 4 VIOLATED, 1 PRESERVED. The 1,013-test suite is green throughout —
every finding below is in the **tests-can't-see-it** class, which is exactly what the audit was for.

**Status legend:** [ ] open · [x] fixed · [~] partially fixed / deferred with reason

## HIGH (ship blockers)

- [ ] **H1 — Skew-curve chart structurally empty for 3 of 4 new horizons** (found independently
  by THREE verifiers: contracts 1, 4, 5). `_skew_curve_points_frame` pre-filters contracts
  through `_signal_area_metrics` (hardcoded 45–150 DTE, a 60d-era assumption) BEFORE applying
  the per-horizon config bands. Intersections: 90:[75,104] ✓; 180:[150,209] → only DTE exactly
  150; 230 and 550 → empty. Probe-verified: tradable DTE-240/500 quotes still render walls of
  `iv=None`/`missing` rows. The milestone's headline feature (long-dated horizons) cannot emit
  skew chart data. **Fix:** per-horizon filter from raw metrics using the config band + the
  delta/IV sanity checks factored out of `_signal_area_metrics`; fixture with DTE-240/500
  contracts asserting non-null IV at 230/550. (`option_signals.py:22-23, 416-437, 853-885`)

- [ ] **H2 — Legacy history backfill manufactures rows (`nan is not None`)** (contract 2).
  `_backfill_legacy_history` gates the 90d row on `record.get("skew_residual_90d") is not None`,
  but `to_dict(orient="records")` yields `float('nan')` for missing values and `nan is not None`
  is True → legacy rows WITHOUT a 90d residual still spawn 90d rows full of NaN. Those NaN rows
  then count toward `history_depth`. **Fix:** route through the NaN-safe `as_float` helper (both
  60d and 90d legs); regression fixture with a missing-90d legacy row. (`option_signals.py:818`)

## MEDIUM

- [ ] **M1 — LIMITED_HISTORY gate counts rows, not usable observations** (contracts 1+2 agree).
  Backfilled 90d rows carry `atm_iv=None` (wide format never stored 90d ATM IV), but
  `history_depth` counts them → with ≥20 legacy days the cost lane silently shows RICH/CHEAP
  from IV/RV alone instead of LIMITED_HISTORY, while `_iv_rank` returns None. The plan's
  Decision 2 explicitly promised calm LIMITED_HISTORY while the 90d series fills. **Fix:**
  `history_depth = history_for_ticker["atm_iv"].notna().sum()`; fixture asserting
  LIMITED_HISTORY until 20 real 90d observations exist. (`option_signals.py:196-209, 663-682`)

- [ ] **M2 — Validator gaps (3 closely related)** (contract 1):
  (a) signal horizon not required ∈ display horizons → validated config can silently kill the
  whole Direction lane (probe: targets=[90,180], display=[180], signal=90 validates, every row
  UNAVAILABLE); (b) display not required ⊆ targets → all-None skew columns for displayed-but-
  never-computed horizons; (c) `optionability_core_horizons` non-emptiness with long-dated
  targets enforced only by a yaml comment — deleting two yaml lines mass-degrades names to
  "thin" (the exact footgun the plan resolved as prevented). **Fix:** three checks in
  `valid_horizon_policies` + runtime tests that mirror the docstring promises.
  (`config_models.py:210-234`)

- [ ] **M3 — Fresh-publish freshness domain ignores schema version** (contract 5; the one
  PRESERVED verdict's main caveat). The OK branch of `_freshness_domains` checks only `usable`,
  never `_schema_version_matches` — post-ship, v2 artifacts on disk + any non-refresh publisher
  → manifest claims `option_artifacts: OK` while serve fails loud on the same artifacts.
  Dishonest split-brain for the carried window. **Fix:** OK requires current schema on all
  required option artifacts, else UNAVAILABLE with a stale-schema reason. (`model_state.py:1258-1274`)

- [ ] **M4 — C4 most-liquid override unguarded against non-displayable stamps** (contract 3).
  The serve override applies any stamped horizon without checking membership in
  `display_horizons_days`; stale artifacts (or extra config bands — validators allow them) can
  stamp a horizon the UI cannot render. **Fix:** gate the override on membership; filter
  `dte_bands` to display horizons inside `_stamp_most_liquid_defaults`; make the (currently
  unused — see L4) `target_horizons_days` threading load-bearing. (`option_trading_data.py:114-128`,
  `option_artifact_frames.py`)

- [ ] **M5 — Stamped `most_liquid_*_expiration` has zero consumers** (contract 3). Persisted and
  round-tripped but nothing renders it; the detail switcher shows slot expirations, which are
  selected by band-fit, NOT by the most-liquid rule — so the stamped expiry can differ from what
  the user sees. **Fix:** render the stamped expiry where the override applies (note line
  "Most liquid: 230d · 2027-01-15") so the column is load-bearing. (`option_trading.py:97-100`)

- [ ] **M6 — 550d realized vol is silently full-history vol** (contract 4). `_realized_vol`
  does `returns.tail(550)` with only a len≥2 guard; ~250 rows of history → "550d realized vol"
  is actually all-history vol, mislabeled, and feeds `iv_rv_ratio_550d`. (Also noted: the
  window is TRADING rows vs an option's CALENDAR days — a pre-existing basis mismatch across
  all horizons, magnified here.) **Fix now:** require ≥80% of the window rows else None
  (honest None beats a wrong number); **defer:** calendar→trading conversion as a recorded
  basis note (changes 90d values; needs its own look). (`features/options.py:199-211`)

- [ ] **M7 — Orphaned dead code from Milestone B: `tier_count` body unreachable inside
  `_median_or_none`** (contracts 1+3 agree). Git pins it to commit `999994a` (my Milestone B
  refactor): `OptionChainScan.tier_count` got orphaned INSIDE `_median_or_none` after its
  return; `liquidity_summary` still calls `scan.tier_count(...)` → would raise AttributeError
  if ever called. **Fix:** delete the orphaned block; delete or restore `liquidity_summary`
  per callers. (`options_liquidity.py:233-242, 436-443`)

- [ ] **M8 — Group-vote recomputes every per-ticker selection** (contract 3). `_stamp_most_liquid_defaults`
  computes `select_ticker_default_window` per ticker, then `select_group_default_window`
  re-runs the identical computation internally. Build-time only, but pointless 2× cost on the
  hot artifact path. **Fix:** compute votes from the already-computed `per_side` map.
  (`option_artifact_frames.py:296-320`)

## LOW

- [ ] **L1 — `OptionSizingRequest` default horizon is the retired 60** (contracts 1+3+4 agree).
  Bare construction (`sizing_request or OptionSizingRequest()` at `option_trading.py:296` and
  the serve proxy path) yields a doomed 60d lookup ("No 60d put candidate"). **Fix:** make
  `build_option_trading_detail`'s currently-unused `target_horizons_days` param load-bearing as
  `default_horizon_days` (serve threads the config signal horizon) and construct bare requests
  from it; retire `PREFERRED_OPTION_HORIZON_DAYS`.
- [ ] **L2 — `signal_horizon_from_row` fallback is literal 60.** Should fall back to None (let
  the chart's documented min-of-points fallback run) rather than a stale constant.
  (`option_signal_render.py:23-33`)
- [ ] **L3 — Stale "Invalid horizon; defaulted to 90d" note when the most-liquid override then
  applies** (e.g. old `?horizon=60` bookmark → note says 90d, page shows 230d). **Fix:** append
  the resolved value after the override.
- [ ] **L4 — `build_option_trading_detail(target_horizons_days=...)` is a no-op param** — serve
  threads config into a parameter the body never reads. Fixed together with L1/M4.
- [ ] **L5 — Signal-area constants vs configurable signal horizon**: validator accepts a signal
  horizon whose band lies wholly outside 45–150 (Direction would read 230d skew while
  Activity/Quality read 45–150 contracts). **Fix:** validate signal band overlaps the signal
  area (cheap), full derivation deferred to a future signal-area-from-config change.

## NIT (recorded, fix opportunistically)

- [ ] N1 — Cross-window tie-break drops `is_standard_monthly` (and documents dropping
  DTE-distance but not that one). Add to the key + docstring. (`option_horizon_selection.py:190-201`)
- [ ] N2 — Schema comparator parity: `_schema_version_matches` accepts "3.9", serve gate is
  strict string-eq. Tighten to normalized string equality. (`model_state.py:1167-1174`)
- [ ] N3 — UNAVAILABLE reason degrades on rebound publishes (stub entries re-derive a generic
  reason instead of propagating the original). Prefer previous domain's reason.
- [ ] N4 — `iv_rank` column in history points is hardcoded None + chart hint says "yet" forever.
  Drop column+hint or compute at build. (pre-existing, not a C regression)
- [ ] N5 — `candidate_puts` keeps (30,60,90) literal defaults; config-model defaults still
  [60,90,120] vs live yaml [90,180,230,550]. Align or make required.
- [ ] N6 — column_help tooltip could take the row-stamped horizon for horizon-qualified text.

## Coverage gap

- [ ] **Serve-purity verifier returned no verdict** (socket death at model switch). Its surface:
  cache-key completeness vs the new stamped columns, guardrail-test bypass paths, NaN rendering
  in new serve helpers. Partially covered by the C5 guardrail test + D1 tests. **Action:**
  targeted re-run of just this surface OR manual pass before ship. (Cache-key note: the stamped
  columns live in the overview artifact, whose content feeds `model_state_manifest_hash` via the
  manifest sha — verify, don't assume.)

## Fix batches (planned order)

1. **Batch A (ship blockers + history honesty):** H1, H2, M1 + tests.
2. **Batch B (validators + freshness honesty):** M2, M3, N2, N3 + tests.
3. **Batch C (selector/C4 coherence):** M4, M5, M8, L1, L4, L3, N1 + tests.
4. **Batch D (flip honesty + dead code):** M6, M7, L2, L5 + tests.
5. NITs N4–N6 opportunistically within the batches touching those files.
6. Full gate → live refresh smoke → ship `dev-vic`→`main`.

## Meta-observations for the retro

- The audit's two HIGHs are both **stale-constant-meets-new-config** bugs (45–150 signal area;
  `nan is not None`) — the class that textual review misses and only adversarial probing with
  live config finds. Worth repeating this audit shape before each milestone ship.
- Three verifiers independently converged on H1 and on the L1 family — convergence is a strong
  realness signal, same as the gold-dial merge audit.
- My own Milestone B refactor left dead code (M7) that a green suite never exercised —
  supports adding an unreachable-code lint rule to the ruff ratchet roadmap.
