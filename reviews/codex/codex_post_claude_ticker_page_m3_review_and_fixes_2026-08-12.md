# Codex post-Claude ticker-page M3 review and fixes

Date: 2026-08-12

Reviewer: Codex coordinated review (master judgment lane plus backend-contract and serve/UI lanes)

Reviewed range: `226670e..3568bc0` on `dev-vic`
Claude handoff reviewed: `reviews/codex/milestones/ticker_page_m3/claude_m3_complete_handoff_2026-08-12.md`

## Executive result

Claude completed the M3 implementation. There is no separate M4 implementation commit; M4 is the documented browser-selector verification harness. I found no P0, security, data-loss, FX-direction, AISC, downside-rate, or finance-source calculation defect.

The review did find several real reader/UI defects. All confirmed findings below are fixed in the current worktree with regressions. Claude should review and retain these fixes, not reimplement parallel versions.

## Findings and completed corrections

| Priority | What was wrong | User impact | Correction now in the worktree |
|---|---|---|---|
| P1 | Parquet nullable strings/booleans were passed through Python truthiness in ticker data, Market behaviour, AISC/downside, Corporate finance, and Options render paths. | Legitimate `pd.NA` cells could crash a ticker page with “boolean value of NA is ambiguous.” This reproduced in the live NEM/AAR.AX paths. | Reused `clean_string`, added one shared `bool_or_false` scalar helper, removed unsafe truthiness from the affected persisted-cell readers, and added nullable regressions. |
| P1 | `_event_period` only looked for `as_of_date`, but live weekly-return rows publish `week_period`. | All 122 downside and 122 upside rows had real counts but no evidence start/end dates, so the UI showed `Period n/a to n/a`. | Parse the published W-FRI `week_period` and persist its actual week-ending dates; retain `as_of_date` compatibility. |
| P1 | A transient artifact read failure was cached under an unchanged manifest identity. | One temporary disk/read error could leave Performance/FX or page-only option data marked corrupt until the server restarted. | `CORRUPT` ticker-page states and `UNREADABLE` page-option states are no longer cached; the next request can recover. Stable generation states remain bounded and cached. |
| P1 | Performance and Currency attribution received only DataFrames, discarding each artifact’s status and reason. | Corrupt/stale Performance falsely said the ticker had no data; corrupt/stale FX silently disappeared. | Pass `TickerPageArtifactState` through `detail_page.py`; both renderers now show a degraded state with the persisted reason. Generic “no rows for this ticker” is reserved for an `OK` artifact. |
| P1 | The v4 page-only option reader required only `ticker` and set `schema_version`. | A checksum-valid but malformed `NONE_LISTED` row could hide a company’s entire Options section. | Validate the complete availability/history columns, outer option-set v4, own artifact v1, non-missing/unique keys, availability/fetch/row-status enums, and capture-quality labels. Any failure becomes `OPTION_PAGE_UNREADABLE`; only a fully validated current `NONE_LISTED` row can hide Options. |
| P2 | Performance chart labels did not pass semantic series keys to the shared chart builder. | Stock reused GDXJ’s colour and Gold reused GDX’s colour, making four lines harder to distinguish. | Pass the stable `stock/gold/gdx/gdxj` keys; regression locks distinct semantic classes/legend swatches. |
| P3 | Ticker-stage persistence telemetry summed four artifacts and omitted FX. | The live stage reported 398,786 persisted rows while it actually wrote 398,969. | Include FX rows and assert persisted telemetry equals the sum of all five artifact row counts. |

## Calculation and logic audit

### FX

- Live artifact: 183 rows — 120 `OK` non-USD windows and 63 explicit USD `NOT_APPLICABLE` rows.
- The non-USD relationship split was 61 `OFFSET`, 56 `SAME_DIRECTION`, and 3 `REVERSAL`.
- The multiplicative identity `USD growth = local growth × FX growth` reconciled to a maximum residual of approximately `1.78e-15`.
- `fx_contribution_pp = usd_return - local_return` reconciled exactly at displayed precision.
- Quote-currency direction, USD normalization, attribution units, window endpoints, and the “share of move”/offset rules were consistent. No FX formula correction was required.

### AISC and downside behaviour

- Available downside/upside rates matched `hit_count / eligible_observation_count`; no bad count or denominator case was found.
- AISC remained in USD/oz and finance-source isolation was preserved. A first audit comparison that appeared to show one mismatch was only `NaN != NaN`; the detailed differing-row set was empty.
- No causal claim is made from AISC versus downside behaviour. The page correctly presents two facts and a peer relationship with the explicit “does not prove causation” caveat.
- The only material downside defect was missing evidence dates, fixed in the producer as described above.

### No double counting found

The reviewed score, percentile, FX, AISC, and hit-rate paths do not add the same economic move twice. The FX block decomposes the local and currency legs multiplicatively and presents the currency contribution separately; it is not added again to a composite score.

## Real-workspace evidence

The coherent refresh already published before these code fixes was:

- Parent refresh: `20260812T102621Z-refresh-04639ab5`
- Ticker-page stage: PASS, five artifacts, 61 active tickers, no alignment warning
- Actual five-artifact rows: 398,969 (`122 + 2,318 + 333,360 + 62,986 + 183`)
- Options: carried-forward schema v3 from 2026-08-11 because the closed-market GDX/GDXJ refresh did not pass option-chain quality gates

Important: the period-date code fix affects the next published ticker-page build. The current immutable artifact still has null start/end dates for the 244 hit-rate rows. Do not mutate that published run in place; publish a fresh coherent refresh when Victor next authorizes the external-data refresh.

## Verification performed

Claude’s already-recorded broad suite, JS parity, mutation, and browser-selector evidence was reused rather than repeated.

Codex ran only changed-area gates:

- Backend producer/cache/stage: **31 passed**
- Ticker sections/behaviour/corporate plus three route integrations: **99 passed**
- Option reader/contracts/persistence/rendering: **110 passed**
- Total focused verification: **240 passed**
- Ruff on all changed source/test files: **clean**
- Live service after restart: `/`, `/ticker/NEM`, and `/ticker/AAR.AX` all returned HTTP 200; NEM had distinct Stock/Gold semantic classes; AAR.AX rendered Currency attribution, AISC, and downside record.

## Deliberately deferred, not newly counted

The known C10 request-snapshot race remains: the cache captures the pointer identity and the five loaders independently resolve the manifest, so a publish exactly between reads could mix generations. This was already accepted/deferred in the plan and belongs with the broader stable-performance/data-spine work, not this bug-fix milestone.

The separate `claude_stable_app_performance_responsiveness_review_2026-08-12.md` also remains deferred at Victor’s request.

## Pre-merge integration audit

- Remote refs were fetched immediately before packaging.
- Exactly one worktree exists: `C:/Users/Emanuel/code/Golden-Vector`, on `dev-vic` at the reviewed M3 head before this fix commit.
- `dev-vic` was 44 commits ahead of and 0 behind `origin/main` before this fix commit.
- No competing local or remote branch was unmerged into `origin/main`. `origin/codex-source-mode` was 62 commits behind, 0 ahead, and already merged.
- Therefore there is no parallel branch touching `model_state.py`, option contracts, ticker serve readers, Candidate Finder, Tool B/D, portfolio artifacts, or schema/manifest code that needs reconciliation before this milestone.
- The high-risk surfaces changed here (option schema/reader, ticker artifact readers, producer evidence dates, and serve renderers) are covered by the focused contract, persistence, cache, producer, renderer, and route gates listed above.

## Claude handoff instruction

1. Keep the current Codex fixes; do not create parallel coercion, version, or validation helpers.
2. Reuse `clean_string`, `bool_or_false`, centralized option contract constants, and manifest-first state objects in future M3 maintenance.
3. Do not rerun the full suite solely for this patch; the focused 240-test evidence above plus Claude’s existing broad evidence is the intended verification record.
4. On the next authorized full refresh, confirm the new hit-rate evidence dates are non-null and the ticker persisted-row telemetry includes the 183 FX rows.
