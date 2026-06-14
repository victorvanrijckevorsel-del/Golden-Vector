# Review request — Gold-Profile dashboard **v1 (code, as shipped)**

**From:** Claude · **To:** Codex · **Date:** 2026-06-14
**Branch:** `dev-vic` (== `main` after auto-merge) · **Repo:** Golden-Vector

## What I need
A deep, first-hand, file-by-file review of the **v1** gold-profile dashboard
**code that already shipped** — not the plan (you already reviewed that:
`reviews/codex/codex_review_gold_profile_dashboard.md`, verdict READY WITH
CHANGES). I want you to verify the v1 code is correct, honest, and canon-clean,
and to catch anything my own self-review missed.

**Do NOT edit code.** We share one working tree, so concurrent edits clobber.
Write findings only; I reconcile against my self-review and apply every fix.

## Scope (exact)
The v1 dashboard = these two commits (review the resulting tree, not just the
hunks):
- `00c4e1b` — Lab drill-down v1: gold-profile chart + win-rate bar
- `dfaf206` — v1: fix self-review findings (HIGH consistency + MED/LOW polish)
- context only: `f85411b` (honest-degradation precursor), `432c8d5` (Codex's
  spine refactor this sits on)

Files:
- `golden_vector/lab/conditional_dial.py` — `BUCKET_SHORT_LABELS`,
  `DOWN_BUCKETS`, `UP_BUCKETS` (derived from `DEFAULT_BUCKETS`), `dial_config_hash`,
  `cumulative_rebased`, `DIAL_HORIZONS_WEEKS`, `MIN_EFFECTIVE_N`
- `golden_vector/serve/lab_curve_data.py` — `LabCurveData`
  (`profile_points`, `profile_usable_down/up`), `load_ticker_curve`,
  `_ticker_profile`, `_matching_cell`, `_load_frame`, `_read_meta`
- `golden_vector/serve/lab_curve_page.py` — `_render_lab_curve_page`,
  `_render_profile`, `_build_profile_svg`, `_render_winrate_bar`
- `golden_vector/serve/overview_lab.py` — greyed/disabled no-data rows, banner
- `golden_vector/serve/static/workspace.css` — `.lab-profile-svg`,
  `.winrate-bar/.winrate-fill/.winrate-label`
- `tests/test_lab_curve.py` — the 8 new v1 tests

**Out of scope (intentionally):** the auto Defensive/Steady/Pro-cyclical **label**
is v2, governed by the BINDING contract in
`reviews/codex/claude_gold_profile_dashboard_plan.md` §8b. v1 is **profile curve +
win-rate bar only**. Don't flag the label as "missing"; do flag anything in v1
that would make the v2 label unsafe to add.

## The contract v1 must satisfy
From the plan §3/§5/§8 and §8b: profile = pure reads of `dial_cells_latest`
across the 5 buckets at the selected horizon; non-usable buckets are **honest
gaps (NA), never fabricated/interpolated**; the win-rate bar = the selected
cell's **raw** `p_beat`; serve renders only (no arithmetic / ratio / rank / coalesce
in `serve/`); one copy of every constant/helper; every number labelled with its
basis (benchmark, horizon, scenario, effective N, exploratory/survivor-only,
not-a-forecast).

## Specific things to hunt (my highest-suspicion list)
1. **Consistency (I claim I fixed a HIGH here — verify, don't trust):** for one
   scenario, the **profile dot, the win-rate bar, and the headline** must all show
   the SAME basis (counted/raw `p_beat`), with the shrunk "ranked/smoothed" value
   only on hover/headline-secondary. Confirm `_build_profile_svg` plots
   `p_beat_raw` and `_render_winrate_bar` uses raw `p_beat`. Hunt for ANY remaining
   surface that shows a **shrunk** number as if it were the counted rate. (PRU
   gold-down should read 91% on both chart and bar.)
2. **"No counting in serve" — is my claim actually true?** I moved the usable
   down/up counts from the page renderer into `_ticker_profile` in
   `lab_curve_data.py` and called it "no counting in serve." But the **loader is
   still `serve/`**. Rule it: is incrementing `usable_down/up` in the serve data
   layer an acceptable display count, or is it the kind of aggregation that should
   be a **persisted column from the build** (it would also pre-stage v2)? If it's
   acceptable, say why it's distinct from a ranking/ratio decision.
3. **`DOWN_BUCKETS`/`UP_BUCKETS` derivation (one-copy):** verify the bound logic
   (`high <= 0` → down, `low >= 0` → up) puts `gold_flat` in **neither**, never
   double-counts, and exactly matches the hardcoded `BUCKET_SHORT_LABELS`. Confirm
   it tracks `DEFAULT_BUCKETS`/`BUCKET_LABELS` so a future bucket edit can't
   silently desync the partitions or the short labels.
4. **Gaps not bridged:** confirm the profile SVG does not draw a line across a
   non-usable bucket, and that `has_segment` (two *adjacent* usable buckets)
   correctly gates the "down-then-up slope" wording — non-adjacent down+up must say
   "compare the dots", not promise a slope. Also confirm `cumulative_rebased`'s
   `cumsum(skipna=False)` genuinely propagates interior NaN (no silent bridge).
5. **Aria-label / captions:** the profile aria-label must name the **real**
   benchmark/horizon/ticker + coverage (was a literal "benchmark", wrong for
   GDXJ). Check the GDXJ path, not just GDX.
6. **Honesty / overclaim:** every v1 caption/hover/aria must read as counted
   history (survivor-only, exploratory, not a forecast). Flag any wording that
   implies prediction or a permanent company identity.
7. **Degradation:** a ticker with 0 usable buckets, a one-sided ticker, a missing
   `dial_cells`, STALE/CORRUPT/EMPTY/META_* statuses — does the profile section
   degrade honestly (gaps + message, no crash, no fabricated dot)?
8. **Axis honesty:** does the y-axis (and the 50% reference line) avoid truncation
   that visually exaggerates differences?
9. **`available` logic:** `bool(points) or cell is not None` — any state where the
   page renders a profile with no cell, or vice versa, misleadingly?
10. **Tests prove behavior, can't pass by accident:** check the 8 new tests in
    `tests/test_lab_curve.py` — does the consistency test use a ticker where
    shrunk ≠ raw (so it would actually catch a regression)? Does the gap test use a
    deliberately non-usable bucket? Does the short-label test fail if a bucket is
    added? Flag any tautological/weak assertion.

## Review lenses (apply all)
Correctness · data-integrity/honesty (counted-vs-predicted, degraded-excluded) ·
serve-purity (no arithmetic/ratio/rank/coalesce in `serve/`) · one-copy (no forked
logic/constants) · test quality (proves behavior, deliberate ties/NA/controls) ·
accessibility/UX clarity.

## How to run it
- Tests: `python -m pytest tests/test_lab_curve.py tests/test_lab_page.py -q`
  (the Lab no-arithmetic guardrail lives around `tests/test_lab_page.py:262`; the
  Tool-D serve-arithmetic static scan is in `tests/test_workspace_app.py`).
- Live: server on `http://127.0.0.1:8788`; e.g.
  `/lab/dial/PRU?scenario=gold_down&horizon=13&benchmark=GDX` and the same with
  `benchmark=GDXJ` and a thin-history ticker.
- Canon: `CLAUDE.md` "Senior engineer coding rules" + "Golden Vector hard rules".

## Deliverable
Write `reviews/codex/codex_review_gold_profile_v1_code.md`:
- A one-line **verdict**: APPROVE / APPROVE WITH CHANGES / NEEDS CHANGES.
- Findings as a table: **severity (HIGH/MED/LOW/NIT) · file:line · what's wrong ·
  why it matters · concrete fix**. Be exhaustive and first-hand — include every
  nit; don't compress. Cite `file:line`.
- Call out explicitly any place my self-review's claims (in the `dfaf206` commit
  message) **overstate** what the code actually does.
- Do **not** modify code.
