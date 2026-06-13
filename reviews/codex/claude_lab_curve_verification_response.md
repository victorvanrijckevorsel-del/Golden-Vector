# Lab Curve Feature — Adversarial Verification Response

**Date:** 2026-06-13 · **Branch:** `dev-vic`
A 4-lens adversarial fleet (correctness / leakage / honesty / repo-canon) verified the
just-implemented Lab relative-performance-curve feature first-hand. Verdict was NEEDS
CHANGES (1 HIGH, 5 MED, several LOW). Every finding was real; all are now fixed with a
test. Final: full lab suite 54 green, workspace integration 68 green, serve guardrails
green, ruff clean.

| # | Sev | Finding | Fix | Test |
|---|-----|---------|-----|------|
| 1 | HIGH | `_cell_field` assumed one column convention; the wide cells mix `p_beat_{b}_shrunk` (mid) with `{b}_effective_n` (prefix), so the shrunk %, Effective N and Wilson rendered as `—` on EVERY drill-down. | `_cell_field` now uses an explicit logical-name→column map. | `test_drilldown_headline_shows_effn_and_shrunk_not_blank` asserts numeric EffN + shrunk %, both benchmarks (was a static-substring test that passed blind). |
| 2 | MED | Headline appended `(thin)` to every usable cell unconditionally. | Dropped the categorical tag; headline shows `Effective N = N independent episodes`, the help-term carries the caution (no new threshold). | covered by the headline render test. |
| 3 | MED | `config_hash` persisted but never validated → a changed bucket/floor (no schema bump) loaded silently. | One shared `dial_config_hash()`; loader recomputes from live config and returns STALE on mismatch. | `test_loader_flags_stale_when_config_hash_mismatches`. |
| 4 | MED | GDXJ `insufficient_history` for a wholly-absent benchmark was `pd.NA`→`None`→treated as sufficient. | Build coerces `gdx/gdxj_insufficient_history = fillna(True).astype(bool)`; render default also flips to insufficient when flag missing. | `test_gdxj_degrades_per_week_independently` + render default. |
| 5 | MED | Serve re-derived the beat decision (`_is_above(alpha>0)`) instead of the persisted `beat`. | Use `point["beat"]`; deleted `_is_above`; SVG colours by `beat`; guardrail now bans `_is_above(`. | serve guardrail (`test_lab_serve_layer_has_no_dial_arithmetic`). |
| 6 | MED | Chart A forward-window gutter was a caption only, never drawn. | SVG reserves + shades a right `+Nw pending` band with a divider. | render test asserts `pending` present. |
| 7 | LOW | Overlap tooltip hardcoded "13+ weeks" on 26/52w lenses. | Interpolates `int(curve.horizon)`. | — |
| 8 | LOW | Dead legacy `dial_table_13w_*` writes (no readers after `lab_data.py` deletion). | Removed the writes + legacy constants; kept `build_dial_table` (parity gate + experiments use it). | parity gate still green. |

**Deferred (noted, low-value):**
- Golden parity fixture has no insufficient-history row — but that path is locked by
  `test_dial_table_insufficient_history_carries_no_numbers` already; not re-blessing the
  frozen golden to avoid provenance churn.
- `cumulative_rebased` cumsum bridges interior benchmark gaps (verified NOT a look-ahead
  leak; the survivor-only weekly frame is contiguous). Assumption documented.
