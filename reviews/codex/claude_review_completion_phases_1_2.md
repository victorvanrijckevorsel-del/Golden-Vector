# Claude review — Completion plan, Phase 0/1/2 (+ Tool D F1–F4)

**Reviewer:** Claude Code (Opus 4.8), first-hand. I read the staged diff file-by-file (`git diff --cached`), traced the data flow through `gold_shock.py` / `analytics.py` / `pipeline.py` / `m4_artifacts.py` / `serve`, hand-checked the survival-line math, and ran an exhaustive adversarial verification sweep (38 agents, every finding re-checked against the actual code, false positives killed).
**Scope:** the staged batch implementing completion-plan Phase 0 (items 1–2), Phase 1 (items 3–6), Phase 2 (items 7–10), plus the Tool D v3 follow-up (my prior review's F1–F4). 28 files, ~1,900 lines.
**Test suite:** **851 passed, 0 failures** (5m18s) on my machine.

## Verdict: **APPROVE WITH CHANGES**

The direction and execution are strong — the gold-shock fork is genuinely unified, the staleness bug is correctly fixed *and wired*, the honesty/UX items are all done, and Tool D F1–F4 are all landed with meaningful tests. **One real correctness gap (H1) must be fixed before this is "done to perfection,"** plus three MEDIUMs and a set of plan-required test gaps. None of it blocks committing as a checkpoint, but H1 + M1–M3 should land before Phase 3 starts.

---

## What is genuinely strong (verified first-hand)

- **Item 3 (staleness) — the live bug you hit is fixed and wired.** `build_portfolio_artifacts` now takes `foundation_manifest_path` and routes via `_portfolio_foundation_manifest_path` ([pipeline.py:388](golden_vector/portfolio/pipeline.py#L388)): refresh (`use_model_state_artifacts=False`, [cli.py:3118](golden_vector/cli.py#L3118)) → fresh `latest_foundation_manifest`; UI edits ([workspace.py:212](golden_vector/serve/workspace.py#L212), default `True`) → pinned model-state. No early model-state publish. Discriminating regression test present ([test_portfolio_m1.py:558](tests/test_portfolio_m1.py#L558)).
- **Item 4 (gold-shock) — one primitive, all forks deleted.** `model/gold_shock.py` applies the `max(0,β)` floor + scenario fraction + 100% clamp in one place; analytics, m4_artifacts, expected_downside, portfolio_totals, and header_context all call it. The forks are gone.
- **Item 6 (currency) — correct.** `CURRENCY_MISMATCH` / `MISSING_FX` lines route through `_missing_value` (value_usd None → never a false P&L), and `_require_positive` guards the valuation boundary.
- **Items 7–10 — all done, not partial.** `[:12]`/`head(8)` truncations removed (issues inline + pairs in `<details>`), linear-estimate + USD-blend caveats render, zero-exposure card (`NO_MEASURED_EXPOSURE`), equity + NAV weights both shown, resilience-coverage line, `/portfolio` gated at the route (403), no `str(exc)` leak in the 500 handler, unified positive-loss sign, pence/GBp hint.
- **Phase 0 — clean and safe.** Local enable via gitignored `portfolio.local.yaml` + `GV_PORTFOLIO_ENABLED` env (no tracked-file edit; `.gitignore:22` confirmed via `git check-ignore`); non-loopback bind refusal preserved; refresh contract intact (portfolio step runs before the single final publish).
- **Tool D F1–F4 — all landed.** F1: `_survival_order_ladder` now sorts `reverse=True` (first-to-break-first as gold falls). F2: `test_workspace_tool_d_serve_layer_has_no_resilience_arithmetic` static-scans the serve module. F3: breakeven is its own headline column. F4: `test_workspace_tool_d_override_does_not_touch_spot_parquet` pins the byte-identical no-persist invariant. Serve does zero arithmetic; no Tool B EBITDA duplication. Survival-line math hand-verified against fixtures.

---

## Findings

### HIGH

**H1 — Item 5 is only half-implemented: stale-FX / non-OK-snapshot lines with a healthy beta are *flagged* but NOT *excluded* from the confident measured-exposure headline or hedge sizing.**
- `_tool_a_exposure_fields` ([analytics.py:85](golden_vector/portfolio/analytics.py#L85)) receives only `(ticker, value_usd, tool_a_row, data_issues)` — it never sees `position_status`. A line with `position_status="STALE_FX"` (or a `WARN`/`FAIL` snapshot status) still carries a real `value_usd`, so with a publishable+modelable beta it returns `effective_exposure_bucket="Measured beta"` ([analytics.py:163](golden_vector/portfolio/analytics.py#L163)).
- That bucket then feeds the headlines: `tool_a_coverage_value_usd` / `tool_a_coverage_fraction` ([analytics.py:218,242](golden_vector/portfolio/analytics.py#L218)), `modeled_gold_down_10_loss_usd` ([analytics.py:219,248](golden_vector/portfolio/analytics.py#L219)), **and** the GDX hedge sizing (`_effective_gold_exposure_usd` → `modeled_short_notional_usd`/put contracts, [m4_artifacts.py:368-384](golden_vector/portfolio/m4_artifacts.py#L368)).
- The plan ([item 5, line 58–60](reviews/codex/claude_completion_plan_portfolio_and_tool_d.md)) explicitly requires these lines be **excluded** from confident headlines + hedge sizing. This also trips the Golden Vector hard rule against presenting degraded data as confident. For your book specifically — foreign names whose FX can go stale while still having a real beta — this silently overstates confident exposure and the modeled gold-down loss, and corrupts the hedge size.
- **Why the tests miss it:** the only stale-FX line in the suite (NEM, [test_portfolio_m1.py:650](tests/test_portfolio_m1.py#L650)) also has `down_beta=0.05`, so it's excluded by the *beta* gate, not by staleness. `MISSING_PRICE`/`MISSING_FX`/`CURRENCY_MISMATCH` *are* correctly excluded (value_usd None) — the leak is specifically `STALE_FX` and `WARN`/`FAIL` snapshot statuses.
- **Fix:** thread `position_status` into the exposure bucketing (or post-process `positions`): route `STALE_FX` / non-OK-snapshot lines to a distinct `"Degraded data"` bucket excluded from `tool_a_coverage_value_usd`, `modeled_gold_down_10_loss_usd`, and `_effective_gold_exposure_usd`, while still showing local value. Add a regression test with a **healthy-beta + stale-FX** line asserting exclusion.

### MEDIUM

**M1 — The min-beta gate now has two sources of truth that can silently drift (re-opening the exact audit-#1 split the unification was meant to close).**
- Portfolio/m4 read the hardcoded module constant: `DEFAULT_GOLD_DOWN_MIN_BETA = 0.10` ([gold_shock.py:10](golden_vector/model/gold_shock.py#L10)) via `GOLD_DOWN_MIN_BETA` ([analytics.py:21](golden_vector/portfolio/analytics.py#L21)) and `m4_artifacts.py:375`. The hedge path reads config: `down_beta_core <= config.down_beta_min_for_scenario` ([portfolio_totals.py:301](golden_vector/hedge/portfolio_totals.py#L301), config `0.10`).
- Both are 0.10 *today* so the surfaces agree — but if the config value changes, portfolio and hedge disagree on which names are modelable. Violates Golden Vector rule #2 (centralize thresholds) and the avoid-duplication guidance.
- **Fix:** thread `app_config.hedge_readiness.down_beta_min_for_scenario` into the portfolio callers (`enrich_portfolio_analytics` + `m4_artifacts`), keeping the module constant only as a standalone default. At minimum add a drift-guard test asserting `DEFAULT_GOLD_DOWN_MIN_BETA == HedgeReadinessConfig().down_beta_min_for_scenario`. (The scenario fraction `-0.10` is similarly hardcoded; config only has a `gold_down_scenarios` list, so consider a single scalar there too.)

**M2 — `effective_exposure_usd` back-solves `loss/|shock|`, so the hedge-sizing headline understates exposure for extreme betas and is shock-fraction-dependent — with no test on the clamped path.**
- [gold_shock.py:114-123](golden_vector/model/gold_shock.py#L114): for a downside shock it returns `loss_usd/|shock|`. Once the 100% clamp bites (effective_beta > 10 at −10%), this diverges from `value × effective_beta` (the unit test encodes 50k vs the true 150k at −20%). This value flows into the hedge headline (`_effective_gold_exposure_usd` sum → `notional = effective_exposure/beta`, [m4_artifacts.py:368-378,167](golden_vector/portfolio/m4_artifacts.py#L368)).
- For realistic gold betas (1–4) new == old, so no practical impact today; but beta>10 is reachable (no upstream cap on `down_beta_core`) and untested through the hedge path.
- **Fix:** either sum the **un-clamped** `value × effective_beta` for the *exposure* headline (keep the clamp only for displayed loss/pnl), or document the "hedge only the loss you can take" semantic at the call site and add a clamped-path (beta>10) test through `build_hedge_sizing_frame`.

**M3 — Per-lot valuation has no `try/except`: one non-finite valuation input aborts the *entire* build instead of degrading a single line.**
- The comprehension at [pipeline.py:184](golden_vector/portfolio/pipeline.py#L184) calls `_value_lot`, which pre-guards `price_local>0` and `fx_rate>0` but passes `quantity=lot.shares` straight into `value_major_unit_price`, where the new `_require_positive("quantity", …)` raises `ValueError` ([valuation.py:67,85](golden_vector/portfolio/valuation.py#L85)).
- Normal shares are validated `>0`, **but** `_positive_float` uses `numeric <= 0`, which is `False` for `nan`/`inf` — so a corrupt/hand-edited store or crafted POST with `shares=nan` passes lot validation and then aborts the whole build (caught as a 400 page at [workspace.py:216](golden_vector/serve/workspace.py#L216)), rather than degrading that one line to a data issue.
- **Fix:** wrap the per-lot valuation in `try/except ValueError` → a `_missing_value(status="INVALID_INPUT")` data issue (or pre-guard `lot.shares>0 and isfinite`). Add a NaN/zero-share test asserting one line degrades, build survives.

### NIT (code)
- **N1** — `stock_clamped_at_zero` is computed ([gold_shock.py:88](golden_vector/model/gold_shock.py#L88)) but no consumer reads it. Either surface it as a caveat where the clamp materially changes the number (ties to Phase 2 item 8 "real selloffs can be worse") or drop the field.
- **N2** — `effective_exposure_usd` means `value×β` for shock≥0 but `loss/|shock|` for shock<0 — two meanings for one field name. Add a one-line clarifying comment.
- **N3** — STALE_FX is detected both at the valuation layer ([pipeline.py:436](golden_vector/portfolio/pipeline.py#L436)) and upstream in normalization QA. The status token is de-duped (`dict.fromkeys`), but `status_reason` narrates the same root cause twice. Consider deriving STALE_FX from the normalization status, or de-dupe the reason text.
- **N4** — `fcf_breakeven`'s `max(aisc, …)` floor ([tool_d.py:613](golden_vector/model/tool_d.py#L613)) is redundant for valid input; it only clamps negative `sustaining_capex`. Validate `sustaining_capex>=0` at ingestion or document the floor's intent.
- **N5** — The raw "Cost-Curve %ile" column is oriented high=worse (low-cost miner shows the *lower* number); only the tooltip saves it ([tool_d.py:412](golden_vector/model/tool_d.py#L412)). The rank is correct (the resilience *component* inverts it). Consider promoting the oriented resilience percentile as the headline, or rename to "AISC %ile (lower=better)".
- **N6** — Spot-view EBITDA anchor at spot×0.90: if Tool B EBITDA is flat across that band, `_ebitda_line_from_tool_b` returns None → `INSUFFICIENT_EBITDA_MODEL` with no survival lines even for a healthy name ([tool_d.py:585-589](golden_vector/model/tool_d.py#L585)). Acceptable conservative fallback; add a documenting test.
- **N7** — `app/config.py` nits: shallow override merge ([config.py:117](golden_vector/app/config.py#L117)) is fine while PortfolioConfig is flat; the env-override hash is over the raw string so `yes` vs `true` hash differently (intent: raw-input audit — fine, just confirm). One-line comments would help.
- **N8** — Out of scope but forward-looking: the N×N correlation heatmap and the now-untruncated data-issues table both render full-size in the first viewport ([portfolio_page.py:268,118](golden_vector/serve/portfolio_page.py#L268)). Fine for now; wrap in scroll/`<details>` if the book grows.

### Explicitly REFUTED (not a defect — flagged here for honesty)
- **Item 6 "currency helper" concern (raised, then killed by verification).** The ad-hoc `.strip().upper()` compare at [pipeline.py:421](golden_vector/portfolio/pipeline.py#L421) does **not** collapse the GBp/GBP minor-unit distinction: that distinction is resolved entirely upstream in `standardize.py` (pence ÷100 applied at standardize time; raw `GBp` tag kept in `feed_currency`, never in `currency`), and `lot.buy_currency` is constrained to major-unit codes. `snapshot.currency` is always major-unit "GBP", so `value_major_unit_price` is the correct call and the compare is a safe currency-identity check. **No change needed** (optional: a one-line comment noting why uppercasing is safe).

---

## Plan-required tests — status

| Item | Required test | Status |
|---|---|---|
| 1 | tracked-false + local/env-true enables; non-loopback bind refused | **PRESENT** |
| 2 | refresh failure before final publish keeps prior model-state | **PRESENT** (generic; portfolio-step branch only transitively covered — NIT) |
| 3 | old vs fresh foundation w/ different **LSE pence/pound** units; model-state unchanged | **PARTIAL** — uses plain USD prices, not pence/pounds; doesn't re-assert model-state unchanged |
| 4 | portfolio **and** hedge agree on neg-beta + high-beta name | **PARTIAL** — primitive-level only; no cross-engine equality assertion |
| 5 | stale FX / missing price don't count as measured exposure | **PARTIAL → tied to H1** — flagging tested; **exclusion neither implemented nor tested** |
| 6 | mismatch visible **+ previous artifacts/store intact** | **PARTIAL** — visibility tested; intactness half not asserted (satisfied by construction — NIT) |
| 7 | no `[:12]` truncation; all rows persisted | **PARTIAL** — code correct, but test only exercises count=1 so a re-added `[:N]` wouldn't be caught |
| 8 | render contains the caveats | **PRESENT** |
| 9 | zero exposure renders the specific message | **PRESENT** (frame-level; a serve-render assertion would be stronger) |
| 10 | route gating / no `str(exc)` / pence hint / field removed | **PRESENT** |
| Tool D F2 | serve-no-arithmetic guardrail test | **PRESENT** |
| Tool D F4 | override doesn't persist parquet | **PRESENT** |
| Tool D | `latest_gold_price_from_history` direct unit test (new `close` fallback) | **MISSING** (NIT) |
| Tool D | config `version` 1→2 round-trip at loading level | **MISSING** (NIT); reject test still pins `version:1` |

---

## Recommended order for Codex (before Phase 3)

1. **H1** — exclude STALE_FX / non-OK-snapshot lines from the measured-exposure headline + hedge sizing (the real correctness fix) + its regression test (item-5 exclusion).
2. **M1** — single-source the min-beta gate from config (thread `down_beta_min_for_scenario`), or add the drift-guard equality test.
3. **M3** — `try/except` around per-lot valuation so a bad line degrades instead of aborting the build.
4. **M2** — fix or document `effective_exposure_usd` in the clamp regime + add the beta>10 hedge-path test.
5. **Test fidelity** — strengthen item-3 (LSE pence/pound units + model-state-unchanged assertion), item-4 (cross-engine agreement), item-7 (>12 rows), item-9 (serve-render), and add the two missing Tool D unit/version tests.
6. **Nits** N1–N8 as convenient.

## Bottom line
Excellent, faithful work — the gold-shock unification, the staleness fix, the honesty/UX pass, and Tool D F1–F4 are all done well, and 851 tests are green. Fix **H1** (the one genuine correctness gap — degraded data silently counted as confident) and the three MEDIUMs, tighten the partial tests, and this batch is ready to commit and build on. The refuted currency-helper item shows the gold-shock/standardize boundary is actually sound.
