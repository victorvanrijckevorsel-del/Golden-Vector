# Fleet review — Corporate Finance ratio info buttons (formula + live numbers)

**Scope:** the metric-formula feature (each ratio's info button shows formula + this ticker's
numbers, on the ticker-detail snapshot and the /tool-b overview).
**Method:** 6 specialist lenses (read-only, first-hand) → each finding re-verified by an
independent skeptic. **20 confirmed, 0 refuted, 1 clean lens (fmt-numeric-td-extra).**
**Outcome:** all material findings fixed in the same commit; new/strengthened tests added.

## HIGH (1 real bug, found by 3 lenses)
- **Detail snapshot cell ≠ its own popover by 100×.** `margin_pct`/`fcf_yield` are stored as
  fractions; the snapshot cell rendered them via the generic `_fmt_value` → `0.57`/`0.39`, while
  the new popover correctly scaled to `57.1%`/`39.4%`. (The /tool-b overview was already correct
  via `as_percent=True`.)
  **Fix:** snapshot ratio cells now render through `metric_result_text` — the SAME per-metric
  format (scale/decimals/unit) the popover concludes with — so the cell and its info button can
  never disagree. This also fixed the snapshot decimals drift on cash margin (2,382.90 vs 2,383)
  and EV/EBITDA (2.00 vs 2.0).

## MEDIUM (fixed)
- **forward_pe overview cell 1dp (`3.3`) vs popover 2dp (`3.29x`).** → overview cell now 2dp.
- **Degraded rows lost Yahoo provenance.** When a ratio is NA, `metric_formula_icon` returns ""
  and dropped the source-provenance icon the old affordance showed. → both surfaces now fall back
  to the provenance icon when the formula icon is empty (`_snapshot_metric_icon`,
  `_overview_metric_icon`).
- **forward_pe provenance shown on detail but not overview.** → overview ratio cells route through
  `_overview_metric_icon`, which appends the same Yahoo provenance `extra` (parity).
- **Dangling "formula. → result"** when every input degrades away → formula now flows straight to
  the arrow (no orphan punctuation).

## MEDIUM (deferred to Codex — his pipeline)
- **Leverage popover names "/ trailing (LTM) EBITDA" but can't show the EBITDA value** because
  `ebitda_ltm_musd` is not a column of the served Tool B output (only `leverage` + `net_debt` are).
  The displayed value is correct; the popover shows formula + net debt + result. Fully completing
  it needs `ebitda_ltm_musd` (AND an `_official` variant for Yahoo-mode source consistency)
  persisted into `TOOL_B_OUTPUT_COLUMNS` + the materialize map — a pipeline change in Codex's area,
  noted in AGENT_SYNC. Naively adding the component without persisting would silently degrade (and
  in Yahoo mode risk a source mismatch), so it's left honest for now.

## LOW (fixed / accepted)
- Added the canon-required static-scan guardrail for `metric_formula.py` (no ratio recompute in
  serve). · Strengthened the weak missing-component test (assert the VALUE bit, not the
  case-coincident label). · cash_margin/ev_ebitda snapshot decimals — fixed by the HIGH fix
  (cells now use the per-metric format).

## Tests added/strengthened
`metric_result_text` matches popover format; leverage coverage; all-components-missing no-orphan;
`_fmt_numeric_td(extra=...)` stays outside `data-order`; `metric_formula.py` serve-arithmetic
guardrail; render-level source-consistency (overview popover result == displayed active value, not
the Our View value).

0 findings refuted — the fleet's verify pass held up first-hand.
