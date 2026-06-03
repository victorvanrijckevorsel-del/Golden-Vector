# Review request for Codex: full whole-tool audit

## Role & mode
You are a senior quant + software engineer doing a **comprehensive, READ-ONLY audit of the ENTIRE Golden Vector tool** — not one subsystem. Do **not** modify code or create commits. Produce one structured findings document.

This is a "review as if the whole thing is about to ship and real money will be risked on it" pass: correctness, data integrity, architecture, the research-vs-implementation match, and honest user-facing framing — across every layer.

## What's already been reviewed (build on these, don't just repeat them)
- `CODE_REVIEW.md` — M1 hedge-readiness engine.
- `reviews/codex/claude_review_codex_option_trading_ui_full.md` — the Option Trading UI (v1a+v1b).
- `reviews/codex/claude_review_codex_m15_v6_checkpoint_a.md` — M1.5 modules.
Treat these as prior context; focus new effort on **cross-subsystem coherence**, **anything not yet audited**, and **the research-grounded correctness** (below). Flag if any prior finding was never resolved.

## The whole surface to audit (by subsystem)
1. **Ingestion & foundation** — `golden_vector/ingestion/*` (fetch, persist, normalization, FX, `options_phase.py`, benchmarks, risk-free rate). Check: currency normalization to USD, FX staleness handling, the **no-mixed-currency** hard rule, per-ticker error isolation, replay snapshotting.
2. **Tool A (structural betas)** — `golden_vector/model/*` (`pipeline.py`, `structural.py`, `labels.py`, `explanations.py`). Check: weekly log-return construction, up/down/core beta math, `score_eligible` gating, confidence/R². This feeds everything downstream.
3. **Tool B (screening/valuation)** — `golden_vector/screening/*` (`pipeline.py`, `manual_data.py`). Check: gold-price-assumption handling, manual-data read, verdict semantics, missing-field handling.
4. **Options engine** — `golden_vector/features/{black_scholes,options,options_chain}.py` and `golden_vector/hedge/{scenarios,candidate_puts,comparison,proxy_hedge,header_context,speculation_section,expected_downside,implied_move,portfolio_totals,sensitivity_ranking,report,_helpers,holdings}.py`. Check: BS put/call correctness + put-call parity, per-contract IV, constant-IV-across-scenarios limitation, beta×gold scaling, breakeven signs, candidate selection/delta targeting, portfolio sizing, the sensitivity ranking.
5. **Option Trading UI** — `golden_vector/serve/{option_trading_data,overview_option_trading,detail_page,detail_panels,workspace,page_shell,http_helpers}.py`. Check: structured-data-not-markdown, composite cache key + freshness, GET-only no-mutation calculator, escaping, fallbacks, empty/stale states.
6. **Workspace serve layer** — overviews, detail, lenses, forms, charts, formatting. Check: routing, escaping, no financial math in the frontend.
7. **Config / provenance / replay** — `golden_vector/app/{paths,config,run_context,replay_manifest,latest_data}.py`, `golden_vector/contracts/{config_models,data_models}.py`, `config/*.yaml`. Check: config registered & hashed, replay snapshot+hash integrity, `verify_manifest`.
8. **CLI** — `golden_vector/cli.py`. Check: command wiring, `refresh`/`status` coverage, fail-loud on missing prerequisites.

## Cross-cutting checks (the high-value part of a *whole-tool* audit)
- **Data-contract consistency:** every column a consumer reads (e.g. `down_beta_core`, `up_beta_core`, `share_price_usd`, `screening_verdict`, `optionability_tier`, `iv_percentile_cross_sectional`) actually exists in its producer's schema. Silent-None coupling is the main risk; flag any drift and recommend a producer↔consumer contract test.
- **Build-sequence rule** (raw → validated features → scoring → UI): is it respected end to end? Any place scoring runs before QA gates, or a downstream tool re-derives something upstream already published?
- **Provenance end-to-end:** can every published number be traced to a hashed source run for replay?
- **Tests:** behavior-focused vs brittle; missing tests for malformed/stale/empty data, currency edge cases, and the research-flagged caveats.
- **Honest user-facing framing:** does the UI ever imply precision or predictive power the data doesn't support?

## Research-grounded correctness (fold this in — it's one lens, not the whole audit)
Read `reviews/codex/research_academic_grounding_gold_model.md` and `reviews/codex/research_options_methodology_and_predictors.md`, then check the implementation against them:
- Per-contract market IV is used (DFW 1998) — no shared/ATM IV mistake; no need for a vol-surface model.
- Constant-IV-across-scenarios understates deep-down-move puts — is it caveated?
- Variance risk premium (Carr-Wu): long options are expensive on average, **but much milder for single names** — is there an honesty disclosure, and do we avoid applying *index-level* magnitudes to *single stocks*?
- `iv_skew` (Xing-Zhang-Zhao crash predictor) and `iv_rv_ratio` (BTZ) are computed but maybe not surfaced — confirm correctness incl. the `put_iv − call_iv` sign convention, recommend surfacing with "validate / may decay" caveats.
- Public put-call ratio is weak (Pan-Poteshman) — not oversold.
- Down-beta is **descriptive, not a return predictor** (Atilgan 2020; Levi-Welch-Karolyi 2020) — nothing implies high-down-beta = higher return; plain beta shown alongside.
- Thin-tail estimates flagged + excluded from any rank (Yamai-Yoshiba; Pitera-Schmidt; Barendse).
- Linear beta×gold% is approximate at −20% (Brennan-Schwartz convexity; Shahzad 2021).

## Optional plan-coherence pass
If time permits, sanity-check the not-yet-built plan `reviews/codex/claude_tool_c_d_plan_v3.md` against the codebase reality (does it consume real columns/paths; is the Tool A weekly-builder reuse feasible).

## Output
Write `reviews/codex/codex_full_tool_audit.md`:
- **Overall grade** + a one-paragraph state-of-the-tool summary.
- **Findings organized by subsystem**, each severity-ordered with concrete `file:line`.
- Clearly separate: **(1) correctness errors / unsound math** (must fix), **(2) data-integrity & cross-subsystem coherence** issues, **(3) research-grounded improvements**, **(4) honesty/labeling gaps**, **(5) test gaps**.
- A short **"top 5 things to fix first"** list across the whole tool.
- Note any **open citation gaps** (cross-commodity betas, AISC elasticity) we should not rely on yet.
- Do **not** rewrite plans or implement fixes. Run read-only checks/tests if useful and report exact commands/results.

## Scale note
This is a large surface. Go subsystem by subsystem; it's fine to take it in passes and note where you spent the most depth. Prioritize correctness and cross-subsystem data integrity over style.
