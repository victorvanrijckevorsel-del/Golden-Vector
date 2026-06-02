# Holistic Put/Call Review

Date: 2026-06-02

Scope reviewed: options ingestion, chain normalization, Black-Scholes helpers, put/call feature engineering, candidate put selection, M1 hedge-readiness report, M1.5 scenario/comparison/header/speculation modules, and the current CLI/report entry point.

## Executive View

The lower-level option infrastructure is already put-and-call aware: raw Yahoo chains persist both sides, normalization accepts `P` and `C`, Black-Scholes delta handles both, feature engineering computes call IV, put IV, skew, straddle implied move, and put/call open-interest ratios. The action layer is not put/call yet. It is put-only by design: `CandidatePut`, candidate grids, premium-vs-downside, scenario P&L, speculation blocks, and current report wording all assume downside puts.

That product boundary is acceptable if M1.5 remains "speculative put buying for gold-down scenarios." It is not acceptable if the next milestone is described as a true put/call product. Calls would need their own candidate object, scenario thesis, upside beta interpretation, Black-Scholes current-value pricing, comparison metrics, and report language. Do not try to slip calls in as a small symmetric variant unless that decision is explicit.

## Checks Run

| Check | Result |
|---|---|
| `python -m compileall -q golden_vector tests` | Passed |
| Focused options/hedge tests | `75 passed in 9.12s` |
| Full test suite | `438 passed in 93.95s` |
| `python main.py hedge-readiness` | Passed; wrote `data/output/hedge_readiness/latest.md` |
| `python -m ruff ...` | Could not run: `ruff` is not installed |
| `python -m mypy ...` | Could not run: `mypy` is not installed |
| `python -m pyright ...` | Could not run: `pyright` is not installed |

The live report still warns that Tool A/B snapshots are stale relative to the options snapshot. That is expected from current local data and is already surfaced in the report.

## Findings

### P1 - "Directly hedgeable" currently means option-chain availability, not necessarily tradable candidate quality

The code labels a ticker `directly_hedgeable` when total open interest clears the threshold and every target horizon has a selected 25-delta put IV (`golden_vector/features/options.py:182-187`). Candidate selection uses computed delta proximity and does not require a non-null midpoint, acceptable bid/ask spread, or any quote-liquidity gate (`golden_vector/features/black_scholes.py:93-107`, `golden_vector/hedge/candidate_puts.py:61-72`). The quote gates exist for straddle implied move (`golden_vector/features/options_chain.py:175-200`) but are not used to qualify candidate puts or optionability. In current data, the report shows 21 directly hedgeable names (`data/output/hedge_readiness/latest.md:13`) while every `implied_move_60d` is `n/a`; GFI is shown as directly hedgeable with `ATM IV 60d` of `307.4%` and no implied move (`data/output/hedge_readiness/latest.md:29-31`). This is the main shipping risk because the future speculation section will turn these labels into action-looking candidate tables.

Recommendation: split "chain available" from "tradable put candidate." Keep optionability for broad universe coverage if desired, but add a stricter candidate gate for action sections: positive bid/ask, non-null mid, spread threshold, minimum OI/volume, plausible IV range, and possibly implied-move gate status. This should be treated as a product-quality fix before making scenario tables prominent.

### P1 - Call support is analytical only; it is not product-ready

Calls are present in lower-level feature engineering: `black_scholes_delta` supports calls (`golden_vector/features/black_scholes.py:17`), normalized chains preserve `P` and `C` (`golden_vector/features/options_chain.py:80-83`), and options features compute `call_result`, `call_iv_25d`, and skew (`golden_vector/features/options.py:102-123`). The action layer is exclusively put-shaped: `CandidatePut` and `build_candidate_put_grid` (`golden_vector/hedge/candidate_puts.py:21`, `golden_vector/hedge/candidate_puts.py:39`), report text says "Candidate puts" (`golden_vector/hedge/report.py:236-237`), and M1.5 scenario math imports `black_scholes_put_price` and models put payoff only (`golden_vector/hedge/scenarios.py:7`, `golden_vector/hedge/scenarios.py:87`). That is coherent for M1.5, but the name "put/call" would overstate the actual capability.

Recommendation: keep the next shipped product explicitly put-only unless a call-side use case is defined. If calls are added, do not fork-and-copy the put code. Add a shared `OptionCandidate`/`OptionScenario` core only after deciding the call thesis: gold-up speculation, covered-call income, call-spread comparison, or something else.

### P2 - Yahoo IV values need a sanity gate before they drive ranking and scenario pricing

Current latest features include IV values that look like Yahoo placeholders or illiquid-market artifacts: `atm_iv_60d` of `3.074221` for GFI, `0.000010` for multiple direct hedgeable tickers, and wide put/call disparities. The code ranks cross-sectional IV directly (`golden_vector/features/options.py:137`) and `_atm_iv` picks the nearest strike by distance and option type without validating IV plausibility or quote quality (`golden_vector/features/options.py:150-156`). M1.5 scenario pricing then uses the candidate IV directly for Black-Scholes current value (`golden_vector/hedge/scenarios.py:87-92`). This can make "cheap IV first" sorting select bad data, not attractive premiums.

Recommendation: add a lightweight IV QA layer before ranking or scenario pricing. At minimum, mark IV unusable below a small floor, above a high cap, or when the quote fails bid/ask gates. For UI/reporting, show "IV unusable" instead of allowing placeholder values to rank highly or price scenarios.

### P2 - M1.5 math modules are built, but the shipped report/CLI does not use them yet

This is expected at Checkpoint A, but it is important operationally. `render_hedge_readiness_report` currently renders holdings, cross-sectional IV ranking, proxy map, and sources (`golden_vector/hedge/report.py:136-148`). It does not call `build_header_context`, `build_speculation_section`, `compute_scenario_bundle`, or `build_comparison_table`. The `hedge-readiness` CLI subparser also has no `--sort-by`, `--quantity`, or `--max-tickers` flags yet (`golden_vector/cli.py:140-141`), and `run_hedge_readiness` starts with empty parameters (`golden_vector/cli.py:555-566`). The latest report confirms no M1.5 scenario/speculation/comparison sections are visible.

Recommendation: this is fine only if everyone remembers the milestone boundary. The next implementation step must include an integration smoke test where `holdings.yaml` is empty and the report still renders the speculation section.

### P2 - Scenario math is directionally honest, but the report must label model assumptions loudly

`compute_scenario_bundle` uses a linear stock-price response to gold scenarios, clamps modeled stock price at zero, prices current value with Black-Scholes, and computes net P&L with a 100-share multiplier (`golden_vector/hedge/scenarios.py:40-116`). That is reasonable for a first calculator. The risk is presentation: "current value if closed today" is actually Black-Scholes re-pricing under constant IV and unchanged time-to-expiry, not a real marked market after gold moves. The code has the data, but the assumption label will be a report-layer responsibility.

Recommendation: when Step 8 renders the report, label the columns exactly as "Current value (BS, const-IV)" and show the 100-share multiplier/contract quantity near every table or section. Do not bury those assumptions in docs only.

### P3 - Day-count convention is inconsistent

Delta calculation uses `CALENDAR_DAYS_PER_YEAR = 365.25` (`golden_vector/features/options_chain.py:12`, `golden_vector/features/options_chain.py:119`), while scenario current-value pricing uses `candidate.days_to_expiry / 365.0` (`golden_vector/hedge/scenarios.py:90`). This is a small numerical difference, not a blocker, but it is avoidable inconsistency in pricing logic.

Recommendation: reuse a single day-count constant for all Black-Scholes calculations.

### P3 - `sort_by` in the speculation builder is validated but unused

`build_speculation_section` accepts and validates `sort_by` against comparison columns (`golden_vector/hedge/speculation_section.py:30-48`), but selection always sorts by `iv_percentile_cross_sectional` ascending (`golden_vector/hedge/speculation_section.py:105-109`). That matches the selection rule, but the parameter name suggests the CLI sort flag might affect the speculation section. This can confuse future wiring.

Recommendation: keep `sort_by` only on the comparison builder, or rename/specify the speculation input if it is meant only as an early validation hook.

### P3 - Header context hardcodes the 60d horizon

Header context compares `implied_move_60d` to modeled downside (`golden_vector/hedge/header_context.py:161-171`) while the rest of hedge readiness has configurable target horizons. The plan says 60d, so this is not currently wrong. It becomes brittle if the default preferred horizon changes.

Recommendation: acceptable for M1.5; if users start changing configured horizons, make the header horizon explicit in config or derive it from the preferred-candidate horizon.

## Architecture Assessment

The architecture is good for the present put-focused use case: data ingestion is separated from features; features are separated from candidate selection; scenario math is pure and testable; comparison/header/speculation modules are small and can be integrated into the report without rewriting ingestion. The best thing about the current design is that M1.5 math can be tested without needing live Yahoo data.

The main architectural weakness is that "optionability" and "tradability" are not separated. For a beginner user making an actual premium decision, this matters more than almost anything else. If the UI says a ticker is directly hedgeable and shows a scenario P&L table, the user will reasonably assume the contract is actionable. The current gates do not yet justify that assumption.

The second architectural weakness is call ambiguity. Calls appear in the data model enough to tempt a quick extension, but the user workflow for calls is not symmetric with puts. For puts, the thesis is "gold down -> gold stock down -> put value up." For calls, the thesis could be directional gold-up speculation, replacing stock exposure, upside convexity, or income/spread construction. Each needs different sorting and interpretation.

## Recommended Next Actions

1. Before Step 8 report rendering, add a stricter "tradable candidate" gate or at least a warning tier for candidate rows with failed quote quality.
2. Keep M1.5 report language explicitly put-only.
3. Add a source-level IV sanity check before IV percentile ranking drives speculation candidate ordering.
4. Integrate M1.5 report sections only after the report tests prove the empty-holdings case renders speculation candidates.
5. Defer real calls until a distinct call workflow is chosen; do not add call scenarios just because the lower layer already has calls.

