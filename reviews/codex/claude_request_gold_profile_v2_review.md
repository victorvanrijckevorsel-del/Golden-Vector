# Review request — Gold-Profile dashboard **v2 (the auto tilt-label, as shipped)**

**From:** Claude · **To:** Codex · **Date:** 2026-06-15
**Branch:** `dev-vic` (== `main`) · **Commit:** `c444485`

## What I need
A deep, first-hand, file-by-file review of the **v2** auto gold-tilt label
(Defensive / Steady / Pro-cyclical) **as shipped in `c444485`**. This is the
highest-risk piece of the dashboard — a labeled *judgment* derived from counted
data — so review it the way the repo canon demands for decision/data code.

**Do NOT edit code.** We share one working tree; concurrent edits clobber. Write
findings only; I reconcile and apply.

## Context you should read first
- The BINDING contract: `reviews/codex/claude_gold_profile_dashboard_plan.md` §8b.
- **My own adversarial review + fixes already applied:**
  `reviews/codex/claude_v2_tilt_label_adversarial_review.md`. I ran a 4-lens panel
  (math / contract / architecture / tests) and fixed **6 MED + LOW/NITs**. Your job
  is to (a) **verify those fixes are real and not overstated**, and (b) find what
  **both** my panel and I missed. Don't just re-report what's already in that record.
- Repo canon: `CLAUDE.md` ("Senior engineer coding rules", "Golden Vector hard rules").

## Scope (exact)
- `golden_vector/contracts/config_models.py` — `GoldProfileConfig` (+ validators,
  `GOLD_BUCKET_NAMES`)
- `config/lab_gold_profile.yaml`
- `golden_vector/lab/conditional_dial.py` — `default_gold_profile_config`,
  `dial_config_hash` (profile param), `cell_bucket_is_usable`, `_gold_tilt_label`,
  `build_profile_artifact`, `PROFILE_COLUMNS`/`PROFILE_CAVEAT`, the `build_and_save`
  wiring (`DIAL_PROFILE_FILENAME`/`_ARTIFACT`, stamped/latest_aliases/meta)
- `golden_vector/serve/lab_curve_data.py` — `LabCurveData` profile fields,
  `_ticker_profile` (shared-helper refactor), `_ticker_profile_label`,
  `load_ticker_curve` wiring
- `golden_vector/serve/lab_curve_page.py` — `_render_tilt_label`, `_render_profile`
- `tests/test_lab_gold_profile.py`, `tests/test_lab_curve.py`,
  `tests/test_config_models.py`, `tests/test_lab_page.py` (guardrail)

## The contract in one paragraph
`gold_tilt` = equal-weighted mean `p_beat_*_shrunk` over the USABLE down buckets
minus the equal-weighted mean over the USABLE up buckets. `tilt >= +T` → Defensive,
`tilt <= -T` → Pro-cyclical, else Steady (`T = tilt_threshold = 0.10`). The label +
tilt are **null unless `label_status == OK`** (both sides meet the usable-bucket
floor); other statuses are `INSUFFICIENT_CROSS_SCENARIO_HISTORY` /
`MISSING_COMPONENTS`. The build computes + persists `dial_profile_latest.parquet`;
serve only **reads** it (no arithmetic, no threshold compare, no label-word literals
in serve). The profile config is stamped into the dial config hash → editing a
threshold makes the artifact STALE.

## Hunt hardest at (and distrust my claims here)
1. **The tilt math itself.** Equal-weighting (not episode-weighted); the threshold
   boundary inclusivity; the label decided on the **rounded** tilt (does the
   persisted `gold_tilt` always agree with the word?); `present_any` → MISSING vs
   INSUFFICIENT; NaN/None shrunk handling; multi-horizon/benchmark grouping. Find
   any input that yields a wrong number, status, or label.
2. **Honesty / overclaim.** Is "13-week historical tilt: Defensive" + the numeric
   derivation + caveat strong enough that it can't read as a forecast or a permanent
   identity? Is a thin/one-sided name ever given a confident label? Is degraded data
   excluded from the label (not just flagged)?
3. **One-copy / serve purity.** `cell_bucket_is_usable` is meant to be the ONE usable
   rule shared by build + serve — verify no forked copy survives. The label basis is
   meant to render the **persisted** tilt-partition count (my M1 fix) while the chart
   slope uses the structural count — confirm those are genuinely consistent and not a
   new divergence. Confirm serve does NO arithmetic / threshold compare and the
   guardrail actually forbids it.
4. **Config / fail-loud.** A typo'd bucket name must fail loud (my M2 fix —
   `buckets_are_known`); confirm it can't be bypassed, and that `GOLD_BUCKET_NAMES`
   can't silently drift from the lab's real buckets. Is `default_gold_profile_config`
   (lru_cache + `ProjectPaths.discover` fallback) a hidden second source of truth vs
   the hash?
5. **Build/serve hash agreement + staleness.** Does the serve staleness check
   compute the SAME hash the build stamped, including the profile config? Could a
   config edit leave a current-looking-but-wrong artifact?
6. **Degradation.** Missing/corrupt/stale `dial_profile` → UNAVAILABLE (label hidden,
   chart renders) — confirm it never crashes and never fabricates a label.
7. **Tests prove behavior.** Can any v2 test pass by accident? Is anything material
   UNTESTED (I deliberately did NOT write a full synthetic `build_and_save` test —
   only a real-artifact guard that skips without data; tell me if that's a real hole)?

## How to run it
- `python -m pytest tests/test_lab_gold_profile.py tests/test_lab_curve.py tests/test_config_models.py tests/test_lab_page.py -q`
- Live (server on `http://127.0.0.1:8788`):
  `/lab/dial/PRU?scenario=gold_down&horizon=13&benchmark=GDX` (Defensive),
  `/lab/dial/KGC?...` (Pro-cyclical), and GDXJ.
- Artifacts already built: `data/lab/dial_profile_latest.parquet` (520 rows).

## Deliverable
Write `reviews/codex/codex_review_gold_profile_v2_code.md`:
- A one-line **verdict**: APPROVE / APPROVE WITH CHANGES / NEEDS CHANGES.
- Findings table: **severity (HIGH/MED/LOW/NIT) · file:line · what's wrong · why it
  matters · concrete fix**. Exhaustive, first-hand, every nit; cite `file:line`.
- Explicitly flag anywhere my `c444485` commit message or my review record
  **overstates** what the code actually does.
- Do **not** modify code.
