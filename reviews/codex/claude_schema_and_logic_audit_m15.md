# Schema & Logic Audit — Hedge Readiness (M1.5)

**Reviewer:** Claude Code (Opus 4.8), read-only audit run *while Codex codes Batch 3*
**Date:** 2026-06-02
**Scope:** data contracts (Tool A, Tool B, options features, manifest, holdings) and the logic of every hedge module **except** `report.py` and `cli.py` — those are being rewritten by Codex right now, so any finding against them would be stale. I'll review them at Checkpoint B.
**Method:** traced every column the hedge modules consume back to its producing schema/code; read the math modules end-to-end for logic defects.

---

## Part 1 — Data-contract map (producer → consumer)

Every column the hedge pipeline reads, where it's produced, and whether the name matches. **All consumed names resolve correctly** (the one historical mismatch, `down_beta_12m` vs `down_beta_core`, was fixed in v6 — confirmed the new modules use `down_beta_core`).

### Tool A — produced by `model/pipeline.py`, schema `ToolAOutput` (`contracts/data_models.py:146`)

| Column consumed | Consumer(s) | Exists in `ToolAOutput`? |
|---|---|---|
| `down_beta_core` | sensitivity_ranking, portfolio_totals, scenarios (via caller), proxy_hedge | ✅ line 166 |
| `up_beta_core` | sensitivity_ranking | ✅ line 165 |
| `confidence_score` | sensitivity_ranking, proxy_hedge | ✅ line 181 |
| `confidence_label` | sensitivity_ranking | ✅ line 182 |
| `score_eligible` | sensitivity_ranking | ✅ line 190 (`bool`, required) |
| `ticker` | all | ✅ line 147 |

### Tool B — produced by the screening pipeline, schema `ToolBOutput` (`contracts/data_models.py:232`)

| Column consumed | Consumer(s) | Exists in `ToolBOutput`? |
|---|---|---|
| `share_price_usd` | portfolio_totals (`_current_stock_price`) | ✅ line 244 (`float \| None`) |
| `screening_verdict` | proxy_hedge | ✅ line 240 (`str`, required) |

### Options features — produced by `features/options.py::compute_options_features` + `rank_options_iv_cross_section`

| Column consumed | Consumer(s) | Produced? |
|---|---|---|
| `optionability_tier` | sensitivity_ranking, report | ✅ `options.py:143/87` (`"none"\|"thin"\|"directly_hedgeable"`) |
| `iv_percentile_cross_sectional` | sensitivity_ranking, report | ✅ initialised None at `options.py:67`, **filled in `options_phase.py` after the batch** via `rank_options_iv_cross_section` |
| `atm_iv_60d`, `implied_move_60d`, `put_iv_25d_60d` | header_context, expected_downside | ✅ generated per-horizon |

### Holdings — `Holding` (`hedge/holdings.py:12`)
- Invariant enforced at load: **exactly one** of `shares` / `dollar_exposure` is set (`holdings.py:69`). portfolio_totals' `mode` derivation (`shares is not None → "shares"`) relies on this invariant — correct and safe.

### CandidatePut — `hedge/candidate_puts.py`
- `underlying_price: float`, `mid: float | None`, `strike: float`, `horizon_days`, `days_to_expiry`, `implied_volatility` — all consumed by scenarios/sensitivity/portfolio and all present. ✅

**Conclusion of Part 1:** no name drift remains. The schemas are internally consistent and the consumers read real columns.

---

## Part 2 — The systemic risk worth fixing (highest-value finding)

### S-1 (High, structural) — Consumers read producer columns by string key with silent-None fallback, and no test guards the contract

Every hedge module reads cross-module columns through `row.get("down_beta_core")` / `as_float(...)` / `row_float(row, "share_price_usd")`. If a producer **renames or drops** a column, the consumer does **not** raise — it silently yields `None` and degrades:
- A renamed `down_beta_core` → every row unranked, P&L all null, ranking section effectively empty.
- A renamed `share_price_usd` → every shares-mode holding "skipped: missing share price," portfolio totals silently near-zero.

The unit tests can't catch this because they build **hand-made fixtures with the correct column names** — they validate consumer logic, not consumer-vs-producer agreement. The `down_beta_12m`/`down_beta_core` issue we already caught was exactly this class, and it survived a full test suite.

**Recommendation (cheap, high-leverage):** add one contract test that asserts the consumer's expected column set is a subset of the producer schema's field names:
```python
def test_hedge_consumes_only_real_tool_a_columns():
    expected = {"ticker","down_beta_core","up_beta_core","confidence_score",
                "confidence_label","score_eligible"}
    assert expected <= set(ToolAOutput.model_fields)   # fails loudly if a producer renames
```
One such test per producer (Tool A, Tool B; and an `optionability_tier`/`iv_percentile_cross_sectional` presence check for the feature producer). This converts a silent-degradation bug into a red test. **This is the single most useful safeguard before M2/M3 add more consumers.**

---

## Part 3 — Logic findings in the math modules

### L-1 (Medium) — The "risk-free rate unavailable; used 0%" note in the sensitivity ranking is misleading
**File:** `sensitivity_ranking.py:138-139`.
The ranking's P&L column is `bundle.rows[0].pnl_per_contract_at_expiry` — the **at-expiry intrinsic** P&L (`max(0, strike−S) − premium`). That value is **independent of the risk-free rate** (rate only affects the *mark-to-market-today* value, which the ranking never shows). So annotating a ranking row with "used 0%" implies the displayed number is affected by the fallback when it isn't.

**Fix:** drop the r=0 note from the sensitivity ranking (keep it where it actually matters — the speculation/scenario blocks that show mark-to-market values). Or, if kept, reword to "(does not affect the at-expiry figure shown)". The Codex test that asserts this note should be updated accordingly.

### L-2 (Medium, product judgment) — `score_eligible` gates *ranking visibility*, not just scoring
**File:** `sensitivity_ranking.py:106, 147` — a row is rankable only if `score_eligible AND down_beta_core is not None`. A ticker with a perfectly good `down_beta_core` but flagged score-ineligible for some unrelated Tool A reason sinks to the bottom with a note, even though it may be a fine speculation candidate. `score_eligible` is a *scoring* gate; using it to hide a name from a *sensitivity* view may be too aggressive.

**Decision needed (Emanuel):** should the ranking sink score-ineligible names, or rank them by `down_beta_core` anyway and just annotate "score-ineligible"? I lean toward **rank-and-annotate** — the down-beta is the ranking key and it's present; hiding the row discards usable signal. Not a code bug; a behaviour choice to confirm.

### L-3 (Medium, watch at Checkpoint B) — Gold-scenario sign convention is now 3-against-1
CODE_REVIEW M1 (deferred in v6) flagged that `scenarios.py` uses **negative** gold scenarios while `expected_downside.py` uses **positive** magnitudes. The new modules add two more **negative**-convention consumers (`portfolio_totals` reads `config.default_scenarios` which are negative; `sensitivity_ranking` hardcodes `-0.10`). So the report Codex is wiring now will render **both** conventions side by side (scenario tables/totals in signed-negative form, the premium-vs-downside cards in positive-magnitude form). That's still correct internally, but the emitter must not cross them or display a raw sign without a label. **Eyeball this specifically in the Checkpoint B sample reports.**

### L-4 (Low) — `sensitivity_ranking` hardcodes the `-0.10` scenario literal
**File:** `sensitivity_ranking.py:131`. The "P&L @ −10%" column hardcodes `gold_scenarios=(-0.10,)`. Fine (the column is by definition −10%), but it's a magic literal duplicated from the config's scenario list. Consider a module constant `RANKING_PNL_GOLD_MOVE = -0.10` so the column header and the value can't drift. Cosmetic.

### L-5 (Low) — `_features_by_ticker` / `rows_by_ticker_dict` keep the *last* row per ticker
**Files:** `sensitivity_ranking.py:168` (`frame.iloc[-1]`); `_helpers.py rows_by_ticker_dict` (dict overwrite → last row wins). The options-feature parquet accumulates history (one row per run), so "last" must equal "latest." This holds today because `_append_feature_rows` appends new rows at the end, but it's an **ordering assumption**, not an explicit "sort by as_of_date / max run." If a future reload ever reorders rows, the ranking would silently read a stale feature row. Cheap hardening: sort by `as_of_date` (or filter to the manifest's `refresh_run_id`) before taking the latest. Not urgent.

---

## Part 4 — What I checked and found correct (no action)

- **Breakeven math** (`scenarios.py:_breakeven_gold_pct`): solving `current_price·(1+β·g) = strike − premium` for `g` is algebraically correct; the `>0 → None + annotation` branch is sound.
- **Strategy P&L** (`scenarios.py`): intrinsic computed internally; all 4 sign rules correct; LONG_PUT path numerically identical to the pre-refactor code (no regression).
- **Black-Scholes call** + put-call parity; `spot=0` limits correct for both.
- **Portfolio aggregation** (post-fix): scenario factor `max(0, 1+β·g)` clamps correctly; loss/loss_pct denominators guard zero; excluded holdings contribute 0 to both numerator and denominator (consistent); hedge cost correctly rate-free (uses market `mid`), which is why dropping `risk_free_rate` was right.
- **Proxy 3-tier** (`_basis_risk_label`): tier boundaries and confidence gating are logically consistent; `medium_limit = min(medium, max_beta_diff)` is redundant given the config validator but harmless.
- **`downside_modelable` boolean** (post-fix): the `assert down_beta_core is not None` invariant holds (modelable ⇒ skip_reason None ⇒ beta present and > min). Clean.
- **Config validators**: ordered proxy bands, 0–1 confidence, protection fractions + uniqueness — all sound.

---

## Priorities for Codex (after Checkpoint B lands)
1. **S-1** — add the producer↔consumer contract tests. Highest leverage; prevents the whole class of silent-drift bugs as M2/M3 grow.
2. **L-1** — remove/reword the misleading r=0 note in the ranking.
3. **L-2** — confirm with Emanuel whether score-ineligible names should sink or rank-and-annotate.
4. **L-3** — verify in the Checkpoint B reports that the two gold-sign conventions are never displayed ambiguously.
5. L-4 / L-5 — opportunistic hardening.

Nothing here is a crash or a wrong committed number. S-1 and L-1 are the two worth acting on; the rest are judgment calls and hardening.
