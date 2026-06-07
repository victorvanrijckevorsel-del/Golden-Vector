# Tool B Simple Fundamentals Plan v2

Status: RECONCILED BUILD PLAN

Inputs:

- Codex v1 plan: `reviews/codex/codex_tool_b_simple_fundamentals_plan.md`
- Claude review: `reviews/codex/claude_review_tool_b_simple_fundamentals_plan.md`
- Emanuel final direction: simple, explainable, industry-standard numbers only.

## Product Decision

Tool B becomes a simple Corporate Finance / Fundamentals tool. It must not publish price targets, best-upside fields, or opaque valuation composites.

The app should show:

- observable market facts;
- company inputs;
- simple gold-price economics labeled as estimates at the stated gold price;
- industry-standard ratios;
- explicit check pass/fail breakdowns.

It should not show:

- Peer P/E target;
- Peak P/E target;
- Peer FCF target;
- Peak FCF target;
- Best target price;
- Best upside %;
- Combined score / Combined verdict home page.

## Required Schema Change

### Remove From Published Outputs

Remove these fields from Tool B, Tool D context, Candidate Finder, detail pages, contracts, tests, manifests/artifact schemas where applicable:

- `adjusted_peer_pe`
- `adjusted_peak_pe`
- `target_price_peer_pe`
- `target_price_peak_pe`
- `target_price_peer_fcf`
- `target_price_peak_fcf`
- `upside_peer_pe_pct`
- `upside_peak_pe_pct`
- `upside_peer_fcf_pct`
- `upside_peak_fcf_pct`
- `best_target_price_usd`
- `best_upside_pct`
- `tool_b_score` as currently defined
- `tool_b_rank` as currently defined

### Keep / Add Industry-Standard Metrics Only

Final Tool B published metric set should include:

- raw facts: `share_price_usd`, `market_cap_musd`, `production_oz`, `aisc_usd_per_oz`, `cash_cost_usd_per_oz`, `net_debt_musd`, `reserve_life_years`, `jurisdiction_tier`;
- gold-price economics at the stated gold price: `gold_price_assumption`, `cash_margin_usd_per_oz`, `margin_pct`, `forward_revenue_musd`, `forward_ebitda_musd`, `forward_net_income_musd`, `forward_eps`, `sustainable_fcf_musd`;
- industry-standard ratios: `enterprise_value_musd`, `ev_ebitda`, `forward_pe`, `fcf_yield`, `leverage` / Net Debt-EBITDA;
- explicit check fields: `fundamental_check_score`, `fundamental_check_rank`, `fundamental_checks_passed`, `fundamental_checks_total`, `fundamental_check_summary`;
- existing provenance and QA fields.

Do not persist the home-grown ratios from v1:

- no `debt_to_mktcap`;
- no `ebitda_to_mktcap`;
- no `revenue_to_mktcap`;
- no `netincome_to_mktcap`.

If a revenue multiple is needed later, use `ev_sales`, but it is not required in this milestone.

## Fundamental Check Score

Replace target-upside-driven `tool_b_score` with `fundamental_check_score`.

Rules:

- It is exactly `100 * passed / total`.
- It must always render with `fundamental_check_summary`, for example `6/7: AISC PASS; Margin PASS; FCF PASS; Reserve life FAIL; Leverage PASS; Forward P/E PASS; Data complete PASS`.
- It is a transparent sorting helper, not a valuation score.
- It derives Layer 1 checks from `evaluate_layer1`; do not reimplement Layer 1 threshold logic elsewhere.
- Add only the forward-P/E check near the verdict logic.

The check set:

- data complete;
- AISC;
- margin percentage;
- FCF yield;
- reserve life;
- leverage;
- forward P/E.

## Remove Combined

Delete the Combined tool entirely. It is a leaf and only the home page consumes it.

Removal scope:

- delete `golden_vector/combined/`;
- remove `persist_combined_outputs`;
- remove combined refresh step and combined artifact from current-state manifests;
- remove combined parquet paths from runtime code;
- remove combined contracts;
- remove combined tests;
- remove `/` Combined overview as the home page.

Replacement:

- `/` becomes Candidate Finder;
- `/candidate-finder` remains as an alias to the same page;
- default home preset is `strong_corporate_finance`;
- move refresh button and model-state banner onto this home Candidate Finder view.

Default preset:

- label: `Strong Corporate Finance`;
- `options_side: none`;
- criteria:
  - `fundamental_check_score` high_good;
  - AISC low_good;
  - Net Debt / EBITDA low_good;
  - FCF yield high_good;
  - margin % high_good;
  - EV/EBITDA low_good;
  - forward P/E low_good;
  - optional reserve life high_good.

Open decision for Emanuel, not blocking: keep or drop a later "Dual Pass / High Conviction" Finder preset that combines strong fundamentals with high gold beta.

## Stale Artifact Handling

After the code migration, existing Tool B artifacts are stale until refresh. Readers must fail loud, not quietly show blanks.

Required guard:

- if a Tool B artifact contains any removed target/upside/best fields, fail with an actionable message: `Tool B output is stale - re-run python main.py refresh`;
- if a Tool B artifact lacks required new fundamental fields, fail with the same actionable message;
- use the same no-silent-failure style as the Candidate Finder join guard.

Operational step:

- explicitly run `python main.py refresh` immediately after the migration before final UI verification.

## Candidate Finder Direction Cleanup

Set field default directions to the quality interpretation:

- AISC: `low_good`;
- leverage / Net Debt-EBITDA: `low_good`.

The bearish-put preset must explicitly override those to `high_good` because that preset is looking for fragility.

Direction remains visible and user-controlled in the UI.

## Checkpoints

### Checkpoint A - Tool B Core

- Remove target-price computation from Tool B.
- Add `enterprise_value_musd`.
- Add fundamental check fields from existing Layer 1 evaluation plus forward-P/E check.
- Replace Tool B ranking with fundamental-check ranking.
- Remove `peer_benchmarks` from config after no code consumes it.
- Add schema-contract tests proving target/upside/best fields cannot return.
- Focused Tool B tests green.

### Checkpoint B - Downstream Wiring

- Candidate Finder consumes new persisted Tool B fields.
- Candidate Finder removes `best_upside` and drops home-grown market-cap ratio criteria.
- Tool D drops `best_upside_pct`.
- Detail pages and data models/contracts remove target/upside fields.
- Stale Tool B artifact guard lands.
- Focused downstream tests green.

### Checkpoint C - Remove Combined and Make Finder Home

- Delete Combined module/tests/persistence/refresh artifacts.
- `/` renders Candidate Finder with `strong_corporate_finance` preset by default.
- `/candidate-finder` still works.
- Refresh button and model-state banner render on the Finder home page.
- Focused route/workspace tests green.

### Checkpoint D - UI Labels, Docs, Refresh, Final Smoke

- Tool B UI shows simple metrics only.
- Forward estimates are labeled as estimates at the stated gold price.
- Override labels say cutoff/minimum, not target.
- Documentation updated.
- Run `python main.py refresh`.
- Full test suite green.
- Browser smoke check: `/`, `/candidate-finder`, `/tool-b`, `/tool-c`, `/tool-d`, and one ticker detail page.

## Acceptance Criteria

- `rg "target_price_|upside_peer_|upside_peak_|best_target_price_usd|best_upside_pct|adjusted_peer_pe|adjusted_peak_pe" golden_vector config tests` returns no active-code/test references, except historical review docs.
- `config/screening_params.yaml` has no `peer_benchmarks`.
- `config/candidate_finder.yaml` has no `best_upside` and no `_to_mktcap` criteria.
- Tool B artifacts expose `fundamental_check_summary` and industry-standard ratios.
- UI contains no Peer/Peak target columns.
- Combined artifacts and code are gone.
- Home page opens directly to Candidate Finder's Strong Corporate Finance preset.
