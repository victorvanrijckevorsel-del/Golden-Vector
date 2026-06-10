# Codex Second-Pass Review - Gold Dial + Fundamentals Plan v2

Verdict: READY WITH CHANGES

The v2 plan is materially stronger than v1. The main architecture choice is right: make the saved Tool B run a dated spot-gold run, compute non-spot scenarios in memory, keep Tool B math in `screening/layer1.py` and `screening/layer2.py`, and add an official Yahoo layer without destructively moving today's hand-entered `company_inputs`. The plan also correctly identifies the current Tool B problems: CLI Tool B resolves the config default at `golden_vector/cli.py:1749`, loads foundation with `include_gold_history=False` at `golden_vector/cli.py:1805`, and the serve override path does the same at `golden_vector/serve/overview_tool_b.py:257-269` while swallowing recompute failures at `golden_vector/serve/overview_tool_b.py:282-283`.

I would not call this "perfect" yet. These changes should be made before build starts.

## HIGH - PR1 must not persist a fake spot run when gold history is unavailable

The plan says PR1 should "keep `resolve_gold_price`/`default_gold_price_assumption=4000` as the explicit labeled fallback only when spot is unavailable" (`reviews/codex/claude_gold_dial_and_fundamentals_plan_v2.md:303-305`). That is still too loose for the canonical saved run. Today `resolve_gold_price()` falls through to config/default/scenario (`golden_vector/contracts/config_models.py:893-904`), which is exactly why Tool B can produce a confusing non-spot "latest" artifact. For the no-override refresh path, missing gold history should fail loud and leave the prior coherent model state intact, not publish a "latest daily gold close" artifact at 4000. Keep explicit CLI custom runs possible, but mark them `gold_price_basis="custom_scenario"` and do not let them become the spot alias consumed by Finder. Concrete plan change: PR1 should state "no override + no valid latest gold close = fail the Tool B step before persistence"; the config fallback is legacy/custom only, not a spot fallback.

## HIGH - Tier 3 lacks a refresh/publish contract for official fundamentals

PR4/PR5 define the additive `fetched_fundamentals` table and raw-statement persistence (`reviews/codex/claude_gold_dial_and_fundamentals_plan_v2.md:327-331`), but the plan does not lock how this data joins the refresh spine. The current system's correctness depends on coherent refresh stages and the model-state manifest (`golden_vector/cli.py:2897-3090`, `golden_vector/app/model_state.py:362-365`). If official fundamentals are just written into SQLite by an ad hoc command, the Tool B parquet, Candidate Finder, and "Market | Ours" view can mix a fresh price snapshot with stale official statements without one central warning. Concrete plan change: PR5 needs a named refresh stage or explicit manual command contract with `source_run_id`, `fetched_at_utc`, stage timing, row counts, and a freshness/alignment contribution. If it is not part of the all-or-nothing model publish, the plan must say how stale official fundamentals are surfaced centrally and excluded from Official ranks.

## MEDIUM - Candidate Finder section is stale relative to staged Finder cleanup

The plan is explicitly verified against `HEAD 39074f1` (`reviews/codex/claude_gold_dial_and_fundamentals_plan_v2.md:5`), but the current working tree has staged Candidate Finder cleanup. The plan still says the Tool D spot guard blanks only `tool_d_quality_rank` (`reviews/codex/claude_gold_dial_and_fundamentals_plan_v2.md:112`). Current staged code blanks multiple Tool D Finder fields via `TOOL_D_FINDER_FIELDS` (`golden_vector/serve/candidate_finder_data.py:41-49`, `:842-846`), and the config now exposes direct resilience fields like `interest_cover_gold_usd`, `debt_stress_gold_usd`, `fcf_breakeven_gold_usd`, and `cost_curve_aisc_percentile` (`config/candidate_finder.yaml:109-140`). PR3 must be updated so scenario injection handles all configured Tool D Finder fields, not just `tool_d_quality_rank`, and so the "default path byte-identical" tests use the new Bull/Bear + Universe framing. Otherwise the implementation will be built against yesterday's Finder contract.

## MEDIUM - Financial status vocabulary is split and lossy

The official table stores per-field `value_status` (`reviews/codex/claude_gold_dial_and_fundamentals_plan_v2.md:174-185`), while the bundle has one row-level `financial_data_status` with `OK | STALE | MISSING | FINANCIALS_UNAVAILABLE | CONTAMINATED` (`reviews/codex/claude_gold_dial_and_fundamentals_plan_v2.md:199-208`). Later, the plan introduces `CURRENCY_BASIS_MISMATCH` as a distinct status (`reviews/codex/claude_gold_dial_and_fundamentals_plan_v2.md:263-267`, `:344`), but that status is absent from the bundle enum. This leaves two engineers free to either collapse currency mismatch into `FINANCIALS_UNAVAILABLE` or pass it through as its own row state. Concrete fix: define one shared enum or explicit mapping: per-field statuses can be detailed, row-level rank eligibility gets a deterministic roll-up, and `CURRENCY_BASIS_MISMATCH` must always exclude Official EV/leverage ranks while rendering a plain-English badge.

## MEDIUM - Existing Tool B override controls need an explicit product decision

PR2 says "one dial" and proposes a Tool B gold-dial form (`reviews/codex/claude_gold_dial_and_fundamentals_plan_v2.md:310-316`), but current Tool B already has a broader override form. It parses gold plus P/E, FCF yield, AISC, margin, reserve life, leverage, and jurisdiction discounts (`golden_vector/serve/screening_overrides.py:28-39`) and renders a "Screening Parameters" panel (`golden_vector/serve/overview_tool_b.py:286-320`). The plan does not say whether those non-gold overrides stay, move behind an advanced section, or are removed. That matters because the user asked for simple true numbers and one gold dial. Concrete fix: PR2 should explicitly keep only gold in the primary dial, and either retire the old non-gold query controls or hide them behind an "advanced assumptions" section with backend-only recompute and tests.

## MEDIUM - PR6 "Market | Ours" needs a concrete difference algorithm

The product decision is sound, but PR6 still only says "where the user's figure differs from Yahoo's" and "largest disagreement first" (`reviews/codex/claude_gold_dial_and_fundamentals_plan_v2.md:333-334`, `:368`). The difference logic is load-bearing and should not be improvised in serve. Define backend fields for each compared ratio: `*_diff_abs`, `*_diff_pct`, `*_diff_status`, `divergent_field_count`, and `max_divergence_pct`. Pin the denominator rule for percentages, especially when values are negative, zero, missing, or nonsensical. Without that, "differences only" can rank a tiny denominator above a genuinely important disagreement.

## NIT - The plan should explicitly list reader/schema contract updates for Tool B spot columns

PR1 correctly says add `spot_gold_usd`, `spot_gold_date`, `gold_price_used`, and `gold_price_basis` to the row dict, output columns, and required columns (`reviews/codex/claude_gold_dial_and_fundamentals_plan_v2.md:303-305`). Add one more explicit line: every Tool B reader that calls `validate_tool_b_output_schema()` must either render these fields or pass through the stale-schema 503. The current schema guard only knows the fundamental columns (`golden_vector/screening/schema.py:26-39`) and current outputs are hard-allowlisted (`golden_vector/screening/schema.py:41-86`), so a partial PR1 will silently drop or fail later if all three places are not updated together.

## What Looks Strong

- The additive official table is the right architecture. `company_inputs` really is today's "our view" layer (`golden_vector/screening/manual_store.py:21-34`, `:514-529`), and avoiding a destructive migration avoids touching `source_verification` status rules (`golden_vector/screening/manual_store.py:267-281`) and confidence logic (`golden_vector/screening/manual_data.py:108-140`).
- The backend boundary is mostly right. Tool B math already centralizes in `compute_tool_b_in_memory()` (`golden_vector/screening/pipeline.py:121-159`), `evaluate_layer1()` (`golden_vector/screening/layer1.py:13-95`), and `compute_layer2_metrics()` (`golden_vector/screening/layer2.py:10-107`). The plan keeps serve as caller/renderer rather than reimplementing formulas.
- The currency and scale warnings are real and correctly prioritized. `layer2.py` currently adds `market_cap_musd + net_debt_musd` without a currency check (`golden_vector/screening/layer2.py:91`), and `layer1.py` divides net debt by EBITDA directly (`golden_vector/screening/layer1.py:66-70`). The plan's statement-currency, FX, `/1e6`, and pence non-conflation tests are necessary.
- Cutting the forward-vs-trailing rank toggle and normalized companion column is the right simplification. Those would add cognitive load without improving the first decision Emanuel needs to make.

## Bottom Line

Buildable after the changes above. I would keep the tiering, but tighten PR1's fail-loud spot behavior and make PR5's refresh/alignment contract explicit before coding. The staged Candidate Finder cleanup also needs to be folded into PR3 before anyone starts implementation.
