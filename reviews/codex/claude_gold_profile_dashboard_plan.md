# Plan — Per-Miner "Gold Profile" Dashboard (clearer than the dots)

**Author:** Claude · **Date:** 2026-06-14 · **Branch:** `dev-vic` (on `main` f85411b)
**Status:** DRAFT for Codex review. No code yet.

## 1. Why (Emanuel's feedback)

The drill-down's forward-alpha **dot scatter is unclear** — ~945 overlapping,
autocorrelated dots; the eye can't aggregate "76% beat" from a cloud, and it
crams *when* + *how much* + *beat/lag* into one dense view. Separately, the
**cross-scenario insight** ("PRU is most resilient when gold falls, weakest when
it rises — defensive") is something the *user should reach themselves*, not be
told by hand. Both point to the same fix: show **how a miner behaves across the
whole gold spectrum at a glance**, and replace the cloud with a clear summary.

## 2. Decisions locked with Emanuel (2026-06-14)

| # | Decision | Choice |
|---|----------|--------|
| D1 | Dashboard hero | **Gold-profile curve across all 5 gold scenarios + an auto plain-English label** (Defensive / Steady / Pro-cyclical). |
| D2 | Within-scenario view | **Win-rate bar + distribution on top; the time view de-cluttered and collapsed below.** |

## 3. Data sourcing — almost all of it is already computed

- **Profile curve** = read the SAME ticker's `p_beat_gdx_shrunk` (+ raw, + median
  alpha) across the 5 buckets `[gold_down_big, gold_down, gold_flat, gold_up,
  gold_up_big]` at the selected horizon, straight from `dial_cells_latest`. No new
  math — 5 existing cells. Insufficient buckets render as honest gaps (NA), never
  fabricated.
- **Win-rate bar** = the selected cell's `p_beat_gdx` (raw) — the share already
  shown in the headline, drawn as a filled bar.
- **Distribution** = the selected (ticker, bucket, horizon, benchmark) scenario
  episodes' `alpha` (already in `dial_episodes_latest`). Shown so the spread is
  visible (see s5 — avoid serve-side binning).
- **Time view** = today's dots, de-cluttered (s5), collapsed under a "when did it
  happen?" toggle.

## 4. THE load-bearing piece — the auto characterization (honest, not opaque)

This is a *derived judgment*; treat it with the rigor the repo's "no opaque
composite scores / label every number's basis / degraded data excluded" rules
demand.

- **Metric (transparent, one definition):** `gold_tilt` =
  `mean(p_beat over USABLE down buckets) − mean(p_beat over USABLE up buckets)`.
  Positive = beats GDX more when gold falls (defensive); negative = more when gold
  rises (pro-cyclical). Use `p_beat_gdx_shrunk` (the ranked number); median-alpha
  tilt is a candidate alt (s7-Q1).
- **Refuse to label on thin data:** require ≥1 usable down bucket AND ≥1 usable up
  bucket (configurable floor). Otherwise render **"not enough cross-scenario
  history to characterize"** — no forced label.
- **Thresholds live ONCE in config** (e.g. `tool_*`/lab config): `tilt ≥ +T` →
  Defensive; `|tilt| < T` → Steady; `tilt ≤ −T` → Pro-cyclical. No hardcoded twin.
- **Wording is counted-history, exploratory, NOT a forecast:** e.g. "Historically
  beat GDX more often when gold fell than when it rose (defensive tilt) — counted
  history, survivor-only, exploratory; not a prediction." The label sits directly
  above the 5 visible numbers it is derived from, so it is transparent, never a
  black box.
- **Computed in the BACKEND, not serve** (the tilt is arithmetic; serve renders
  only). Compute the per-(ticker, horizon) `gold_tilt` + label in the lab build and
  persist it (a small `dial_profile_latest.parquet`, or columns on the cells
  meta). Serve reads + draws. Add it to the serve no-arithmetic guardrail.
- It is industry-recognizable framing (defensive vs cyclical), not an invented
  blended score — consistent with "industry-standard metrics only".

## 5. Rendering (serve, render-only)

- **Profile curve (hero):** x = the 5 gold scenarios (down-big → up-big), y =
  P(beat GDX). One marker per usable bucket; gaps for insufficient. A reference
  line at 50%. Hover shows raw P(beat), median alpha, effective N for that bucket.
  The auto-label + the "down-tilt/up-tilt" annotation beneath it.
- **Win-rate bar:** a filled horizontal bar = the selected scenario's raw P(beat),
  labelled "X% of the <scenario> weeks beat GDX (median <a>%, N=<eff>)".
- **Distribution:** to avoid serve-side binning, draw a **1-D strip** of the
  scenario episodes' alpha (each week a tick on a +/- axis, zero line, median
  marked) — shows where the mass sits without computing histogram counts in serve.
  (Alt: persist histogram bin counts in the build; s7-Q2.)
- **Time view (collapsed):** reuse today's dots but show only the independent
  (non-overlap-anchor) episodes — ~1/h the count — so it's readable, under a
  "when did it happen?" `<details>`.
- New serve module(s) added to the global no-arithmetic guardrail sweep.

## 6. Architecture / canon

- Backend computes (the tilt + label persisted in the build); serve filters +
  draws. Compute-once → persist → serve reads. One copy (reuse the cells/episodes
  artifacts + existing SVG helpers; no forked math). Every number labelled with
  its basis (benchmark, horizon, scenario, effective N, exploratory/survivor).

## 7. Open decisions (my recommendation; Codex/Emanuel to confirm)

1. **Profile y-axis = P(beat) vs median-alpha.** Rec: **P(beat) shrunk** as the
   primary (it's the ranked number + matches the table), median alpha on hover and
   as a secondary toggle (magnitude is half the "defensive" story — PRU is +25% vs
   −10%). Possibly show both as twin small charts.
2. **Distribution: 1-D strip (no serve math) vs persisted histogram bins.** Rec:
   start with the **strip** (simplest, no new artifact); add binned histogram only
   if the strip reads poorly.
3. **Where it lives.** Rec: fold into the existing `/lab/dial/<ticker>` page as the
   new top section (profile + label), with the selected-scenario bar/distribution
   below and the time view collapsed — one page, progressively detailed.
4. **Characterization basis.** P(beat)-tilt only, or P(beat)-tilt + alpha-tilt
   combined? Rec: **P(beat)-tilt** for the label (cleaner, one number), show alpha
   context but don't fold it into the category (keep the label simple + honest).

## 8. Simplest-first / staging

- **v1:** the profile curve (5 existing P(beat) values) + the win-rate bar — both
  are pure reads, no new artifact, big clarity win immediately.
- **v2:** the auto characterization label (the one piece needing the build-side
  tilt + config thresholds + the refuse-on-thin-data rule) — the part to review
  hardest.
- **v3:** the distribution strip + the collapsed de-cluttered time view.

## 8b. Codex review reconciliation — v2 contract (BINDING; verdict READY WITH CHANGES)

All 5 MED + 2 LOW accepted. Codex's coverage measurement independently
re-verified by me: at 13w 54/65 names have >=1 usable down AND >=1 up bucket, but
**0/65 have both down + both up**; 26w has 0 names with both sides. So the profile
is in practice a **gold_down-vs-gold_up comparison** for most names — the design
must reflect that, not imply a full 5-point spectrum.

1. **Real validated config, not a constant (MED).** Add a Lab gold-profile config
   model (`config_models.py` + a YAML) — fields: `tilt_threshold: 0.10`,
   `min_usable_down_buckets: 1`, `min_usable_up_buckets: 1`,
   `down_buckets: [gold_down_big, gold_down]`, `up_buckets: [gold_up, gold_up_big]`,
   `default_profile_horizon: 13`. Validate signs/ranges. Stamp into the Lab
   `dial_config_hash`; test that changing a threshold makes the artifact STALE.
2. **Exact "usable" (MED):** `gdx_insufficient_history == False` AND
   `p_beat_gdx_shrunk` non-null. Persist `usable_down_bucket_count`,
   `usable_up_bucket_count`, `used_buckets`. Tests: one-sided history, null shrunk,
   threshold-edge.
3. **Coverage honesty (MED, verified):** keep the `>=1/>=1` floor, but render the
   basis next to the label — e.g. "based on 1 down bucket and 1 up bucket at 13w".
   The profile chart shows the 5 scenario slots with **explicit gaps** for
   non-usable buckets; never implies the whole spectrum. A stricter
   "whole-spectrum" label, if ever wanted, is a config choice, not hidden.
4. **Separate run-stamped artifact (MED):** `dial_profile_<run>.parquet` +
   `dial_profile_latest.parquet`, one row per `(ticker, horizon_weeks, benchmark)`:
   `gold_tilt`, `gold_tilt_label`, `label_status`, the component down/up mean
   values, `usable_down/up_bucket_count`, `used_buckets`, config hash, caveat. Add
   to `run_stamped_artifacts`, latest aliases, required-column + stale-schema tests.
   NOT meta columns.
5. **Horizon-scoped wording (MED):** schema + UI say "13w historical tilt" /
   "selected-horizon tilt"; never bare "this miner is defensive" without horizon,
   benchmark, and coverage count.
6. **Equal-bucket weighting (LOW):** `gold_tilt` = mean over usable down buckets
   minus mean over usable up buckets — **equal-weighted across usable buckets, NOT
   episode-weighted** (so rare extreme regimes aren't dominated). State this in the
   artifact metadata.
7. **Machine-readable status (LOW):** `label_status` in
   `{OK, INSUFFICIENT_CROSS_SCENARIO_HISTORY, MISSING_COMPONENTS}`;
   `gold_tilt_label` is null unless status is `OK` (so no screen can rank/filter on
   a placeholder).
8. **Serve guardrail (LOW):** extend the Lab no-arithmetic sweep to the new profile
   reader/render; forbid `.mean(` / `.groupby(` / `p_beat_gdx_shrunk` aggregation
   and the literal label words (`Defensive`/`Steady`/`Pro-cyclical`) being decided
   in serve. Serve only chooses display text from persisted `gold_tilt_label` +
   `label_status`.

Net effect: the label becomes a fully-specified, config-driven, horizon-scoped,
coverage-honest, build-computed artifact field — not a hidden composite. **v1
(profile curve + win-rate bar, pure reads) is unaffected by these and can ship
first; the contract above governs v2 (the label).**

## 9. Review asks for Codex

1. Is the `gold_tilt` definition + the refuse-to-label floor honest and
   un-gameable, and are the thresholds correctly config-sourced (no twin)?
2. Is computing the tilt/label in the build (not serve) the right seam, and is a
   small `dial_profile` artifact better than columns-on-cells?
3. Is the 1-D strip an acceptable distribution view that keeps serve render-only,
   or should bins be persisted?
4. Any PIT/honesty gap: the profile is counted history conditional on the
   user-chosen scenario — is the "defensive (historical, not a forecast)" wording
   strong enough to avoid implying prediction?
5. Anywhere this forks existing logic (cells/episodes reads, SVG, bucket order).
