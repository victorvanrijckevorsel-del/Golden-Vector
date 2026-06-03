# Codex Brief — Shipping-Safety Fixes (from the full-tool audit)

**For:** Codex
**From:** Claude Code (Opus 4.8)
**Branch:** `dev-vic`
**Source:** `reviews/codex/codex_full_tool_audit.md` (your audit, grade "READY WITH IMPORTANT FIXES") + the two research docs (`research_academic_grounding_gold_model.md`, `research_options_methodology_and_predictors.md`).
**Nature:** these are NOT math-engine rewrites. They are honesty/labeling, surfacing already-computed signals, a documentation+test of the Tool A formula, and replay/robustness hardening. The option pricing core is sound — do not change it.

## Locked decision (no need to re-litigate)
**Tool A down-beta:** KEEP the current split-sample conditional (down-week) OLS beta. Do NOT switch to Estrada/D-CAPM. The fix is **documentation + a formula contract test** only (Batch 2, item 6). We use down-beta descriptively (rank how hard a miner falls), not to predict returns.

## How to work
Build continuously to completion — **deep self-review after every step, a deeper holistic review at each checkpoint** (logged in `reviews/codex/codex_shipping_safety_progress.md`), **don't stop and wait** unless you hit a genuine blocker. One commit per item + a self-review-fixes commit per batch. **No `git push`.** No live data in tests. Pre-flight: confirm branch, `pytest -q` baseline (should be 550).

---

## Batch 1 — User-facing honesty (the tool is for speculation; these matter most)
1. **Long-option negative-expectancy disclosure.** Add a plain-English caveat wherever speculative puts/calls and the sizing calculator are shown — `golden_vector/serve/detail_panels.py` (option panel / calculator) and `golden_vector/hedge/report.py:~677` (speculation candidates). Wording: *"Buying puts/calls can be right on direction and still lose money if the move is too small or too slow — option premiums include a cost for volatility risk."* Keep it honest but **do not** overstate: the effect is real but **milder for single stocks than for indexes** (Carr-Wu 2009) — don't quote index-level straddle-loss magnitudes as if they apply to single miners.
2. **Relabel modeled values as modeled, not quotes.** `golden_vector/hedge/report.py:~899` labels scenario columns "Expiry quote / Current quote" — these are **Black-Scholes-modeled** values. Rename to **"Modeled value at expiry / Modeled value now"** and repeat the constant-IV assumption near the table. (The UI in `detail_panels.py` is already clearer — make the markdown report match.)
3. **Flag extreme gold-shock rows as approximate.** `golden_vector/hedge/scenarios.py:~126` uses a linear `price × (1 + beta × gold%)`. In both the report and the UI, mark the **−15% / −20%** rows "approximate — linear beta understates real downside; operating leverage / balance-sheet stress can make moves non-linear" (Brennan-Schwartz convexity; Shahzad 2021).
4. **Label the Sensitivity Ranking descriptive, not predictive.** `golden_vector/hedge/report.py:~545` + the Option Trading overview: state it is a **"descriptive stress-sensitivity view (how a stock has behaved when gold fell), NOT a forecast of returns"** (Atilgan 2020; Levi-Welch-Karolyi 2020). Ensure **plain beta (`structural_delta_core`) is shown alongside `down_beta_core`**.
- **Tests:** assert each disclosure/label appears in the markdown report output AND the option-trading lens HTML.
→ Self-review gate, then **Checkpoint A**: paste a sample report + the option panel showing the new labels.

## Batch 2 — Surface computed signals + document the Tool A formula
5. **Surface `iv_skew` and `iv_rv_ratio`.** Both are computed in `golden_vector/features/options.py:137,140` but not shown. Surface them in the Option Trading tab + report as **context signals with caveats**:
   - `iv_skew` (put_iv − call_iv): a **crash-risk / downside-demand** signal (Xing-Zhang-Zhao 2010). Confirm the sign reads "more positive = downside protection more expensive = more crash-risk priced in." Label "in-sample signal, validate, may decay — not a trigger."
   - `iv_rv_ratio` (implied vs realized): an **"options look expensive vs how much the stock actually moves"** context (BTZ 2009). Short-horizon only.
   - Keep the **public put-call ratio as context only** (it's a weak signal — Pan-Poteshman; do not surface it as predictive).
6. **Document the Tool A beta formula + add a contract test.** In `golden_vector/model/structural.py` (docstrings for `compute_regression` and the up/down split) and the Tool A explanation text, state precisely: **"split-sample conditional beta — OLS slope (with intercept) of weekly stock log-returns on weekly gold log-returns, computed separately over gold-up and gold-down weeks."** Do NOT call it D-CAPM/Estrada. Add `tests/test_structural_beta_formula.py`: a deterministic fixture with hand-computed numbers that pins full beta, up-beta, and down-beta (catches any silent formula change).
- **Tests:** signals render with caveats; the formula test locks the math.
→ Self-review gate, then **Checkpoint B**: show the signals in the UI + the formula test.

## Batch 3 — Provenance & robustness
7. **Make replay verification transitive.** `golden_vector/app/replay_manifest.py:~171` `verify_manifest` checks captured manifests but NOT the per-snapshot `sha256` entries inside them (`persist_options.py:~29` records them). Extend `verify_manifest` to walk those nested entries and confirm each underlying parquet is present and unchanged — OR, if you keep it manifest-only, make the command output explicitly say "manifest-level only." Prefer transitive. **Test:** a changed/missing nested options (and foundation) parquet is detected.
8. **Centralize the gold-scenario sign convention.** `expected_downside.py:~32` uses positive downside magnitudes; `scenarios.py:~75` uses signed returns (−0.10). Add one small conversion helper + a **guard test that fails loudly** if a positive magnitude is passed into the signed engine (prevents silently modeling upside as downside).
9. **Broaden the producer↔consumer contract test.** `tests/test_hedge_data_contracts.py` only checks a minimal column set. Extend it (fixture-based) to cover **every** field consumed by the hedge report, Option Trading UI, sensitivity ranking, and portfolio totals (`underlying_price`, `atm_iv_60d`, scenario fields, run ids, candidate metadata — see `serve/option_trading_data.py:~375`, `hedge/sensitivity_ranking.py:~113`, `hedge/report.py:~1070`).
→ Self-review gate, then **Checkpoint C**: completion report (what changed, test deltas, the disclosures/labels list, replay-verification behavior).

---

## Self-review gate (run after every item; deeper at each checkpoint)
Read your own diff hunk-by-hunk (scoped files only, no stray edits); `pytest -q` green and count ≥ baseline + new; verify the item against the audit finding it fixes; for the honesty items, confirm the exact wording is present in BOTH the markdown report and the UI; confirm you did **not** alter the option pricing math. Fix, commit, log, continue.

## Out of scope (do NOT do here)
- No Tool C/D work (separate milestone).
- No change to Black-Scholes / scenario math, candidate selection, or the down-beta calculation (document only).
- No vol-surface model (the research says per-contract IV is correct).
- No new data fetchers.

## Done =
All 9 items shipped with tests; full suite green; disclosures present in report + UI; replay verification behavior explicit and tested; the Tool A formula documented + locked by a test; completion report written. Then stop for review.
