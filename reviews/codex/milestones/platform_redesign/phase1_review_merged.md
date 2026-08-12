# Phase 1 — merged Claude + Codex review findings

- Date: 2026-08-12
- Reviewed implementation snapshot: `b542fe0` (`c7e90db..b542fe0`)
- Round-1 fix commit: `a9f2faa`
- Wave-2 fix commit: `8886185`
- Baseline evidence commit: `8254909`
- Sources:
  - `reviews/codex/milestones/platform_redesign/phase1_review_round1.md`
  - `reviews/codex/codex_review_phase1_ticker_correctness_2026-08-12.md`
  - `reviews/codex/milestones/platform_redesign/phase1_baseline.md`

This document reconciles the two reviews and their dispositions. The final self-review and gate
closure are recorded at the end only after they actually finished.

## Counting and overlap

Claude confirmed **10 reports** from its adversarial review. `F1` and `F2` were two reviewers'
reports of the same scenario-card labelling defect, so they required one implementation fix; this
is why the round-one fix commit describes nine verified findings while the source review records
ten confirmed reports.

Codex reported **14 findings**. For comparison below, `C1`–`C14` are local identifiers assigned in
the order the findings appear in the Codex report; they do not replace its original severity
labels. Three Codex findings overlap Claude findings, ten are distinct Wave 2 findings, and one is
an evidence/process finding.

## Merged disposition table

| Claude finding(s) | Codex finding | Relationship | Finding | Disposition | Resolution evidence |
|---|---|---|---|---|---|
| F0 | C12 (P2) | Shared State-A/out-of-range root | An out-of-range spot made the slider inert but the old disabled path erased trustworthy spot values; Codex also found that the Node out-of-range test encoded the opposite behaviour. | **Fixed round 1** | `a9f2faa` split artifact availability from `scenario_enabled`, retained the five persisted spot values, kept the slider inert, and corrected the regression coverage. |
| F1 + F2 | C2 (P1) | Direct overlap; Claude counted two independently confirmed reports | An active scenario headline was still labelled by each card's spot-basis line. | **Fixed round 1** | `a9f2faa` updates each card basis to scenario + baseline while moved and restores the exact original basis on return/reset; the Node assertions cover those transitions. |
| F3 | C11 (P2) | Direct overlap | Count charts could draw distinct ticks with duplicate rounded labels. | **Fixed round 1** | `a9f2faa` added the count-mode minimum tick step and regression coverage. |
| F4 | — | Claude-only | The disagreeing-currency branch in the share-price view lacked a regression. | **Fixed round 1** | `a9f2faa` added the mixed USD/CAD case and proves the chart is withheld. |
| F5 | — | Claude-only | The wider price-mode plot gutter was not pinned by tests. | **Fixed round 1** | `a9f2faa` added price/indexed gutter-coordinate assertions. |
| F6 | — | Claude-only | `.scratch/` was not ignored; the unrelated root `naukri.md` was also noticed. | **Fixed round 1** | `a9f2faa` added `.scratch/` to `.gitignore`. Victor's `naukri.md` remains untouched and untracked. |
| F7 | — | Claude-only | The bare “Share price” no-drawable fallback lacked a regression. | **Fixed round 1** | `a9f2faa` added the missing fallback assertion. |
| F8 | — | Claude-only | The overlay payload carried a dead `base` key that no browser consumer read. | **Fixed round 1** | `a9f2faa` removed the dead key and updated the related tests. |
| F9 | — | Claude-only; resolved by the F0 refactor | `disabled_attr` and `dial_unavailable` duplicated the same availability predicate. | **Fixed round 1** | `a9f2faa` consolidated the decision around the single scenario-availability predicate. |
| — | C1 (P1) | Codex-only | Missing/non-finite spot values were not consistently State A; infinity could make strict JSON embedding crash the route. | **Fixed wave 2** | `8886185` resolves spot once with `optional_finite_float`, reuses that value through markup/state/payload, adds a concrete reason, and covers `None`, `NaN`, and ±Infinity. |
| — | C3 (P1) | Codex-only | Removing missing OI samples made the SVG bridge gaps and visually invent a move. | **Fixed wave 2** | `8886185` splits each line into contiguous segments and preserves isolated one-point segments, with gap regressions. |
| — | C4 (P1) | Codex-only | Two-decimal price mode collapsed valid sub-cent prices to `USD 0.00`. | **Fixed wave 2** | `8886185` resolves one chart-wide price precision from the drawn scale and applies it consistently to axis, crosshair payload, and accessible table. |
| — | C5 (P1) | Codex-only process finding | The reviewed commit did not contain committed baseline evidence, and the requested before screenshots were absent. | **Process-resolved** | Baseline evidence was committed in `8254909`. Victor explicitly deferred the 1440/1024/390 before/after screenshots to the batched Phase 4 visual gate; `phase1_baseline.md` records the decision and reproducible before-capture recipe. |
| — | C6 (P2) | Codex-only | `align_to_step()` used Python ties-to-even instead of the browser's exact-half-up rule. | **Fixed wave 2** | `8886185` uses Decimal grid arithmetic with half ties toward the higher value and adds half-step tests. |
| — | C7 (P2) | Codex-only | Slider serialization could discard a fractional grid origin or emit above the highest legal step. | **Fixed wave 2** | `8886185` adds optional maximum-grid capping to `align_to_step()` and serializes using the greater precision of minimum and step, with both edge geometries tested. |
| — | C8 (P2) | Codex-only | Fractional-step scenarios announced a rounded price different from the actual control value. | **Fixed wave 2** | `8886185` derives scenario-price formatting from the configured step/minimum and uses it for visible output, bases, ARIA text, and announcements; the Node suite includes a fractional-grid case. |
| — | C9 (P2) | Codex-only | Put and total OI inherited the same fallback visual series key. | **Fixed wave 2** | `8886185` supplies three explicit, distinct OI series keys and tests their line/legend mapping. |
| — | C10 (P2) | Codex-only | Stock-only Share price leaked benchmark status/trim notices. | **Fixed wave 2** | `8886185` scopes drawable, marker, and trim rows to stock in price view while retaining all benchmark notices in Compare. |
| — | C13 (P3) | Codex-only | The real-JavaScript state-machine suite covered only Our View, not Yahoo. | **Fixed wave 2** | `8886185` parameterizes the relevant Node flows across distinct Our View and Yahoo payload sentinels. |
| — | C14 (P3) | Codex-only | Count mode silently inherited the indexed builder's default base of 100 unless every caller overrode it. | **Fixed wave 2** | `8886185` makes the anchor part of the display-mode contract: indexed uses `base`, count owns zero, and price has no anchor; the OI caller no longer supplies `base=0`. |

Coverage check: the Claude column accounts for `F0` + `F1/F2` + `F3`–`F9` = **10
confirmed reports**. The Codex column accounts for `C1`–`C14` = **14 findings**.

## Verification available so far

No full suite was run for this Wave 2 work, per Victor's explicit instruction to use proportional,
focused verification for Phase 1. The committed pre-change baseline remains **2182 passed** in
`phase1_baseline.md`; it is baseline evidence, not a post-Wave-2 result.

| Check | Result | Scope note |
|---|---:|---|
| Wave-2 focused group 1 | **190 passed** | Common helpers, Corporate Finance, gold-dial Node behaviour, overlay chart, performance section, and Options tests. |
| Wave-2 focused group 2 | **35 passed** | Ticker-page JS parity and workspace-shell tests. |
| Wave-2 focused group 3 | **157 passed** | Workspace-app and redesign-route tests. |
| `tests/test_gold_dial_js_behavior.py` Node shim | **16 passed** | Included within focused group 1; called out separately because it is the real-JavaScript state-machine gate. |
| Ruff on all Wave-2 touched Python files | **clean** | No lint findings. |

The three focused pytest groups total **382 passed**. The 16 Node-shim tests are a subset of the
190-test first group and are therefore not added again.

## Gate status and completion note

**Phase 1 is complete on `dev-vic` at `8886185`.** What shipped:

- a browser-normalized, baseline-anchored gold-dial state machine with exact spot semantics,
  honest disabled states, one active headline value, clean return/Reset, and source-paired
  real-JavaScript coverage;
- indexed, price, and count overlay display contracts with truthful units, accessible-table and
  crosshair parity, gap preservation, low-price precision, and honest OI series identity;
- all 10 Claude reports and all 14 Codex findings resolved, including the process disposition for
  baseline screenshots explicitly deferred by Victor to the Phase 4 batched visual gate.

The first Wave-2 skeptical pass found one additional fractional-grid-origin formatting defect. It
was fixed before `8886185`; the follow-up read-only review of `4d97fb9..8886185` returned **zero
actionable findings**, closing the review loop. The final post-fix focused gate is **382 passed**
across the three prescribed groups; Ruff and `git diff --check` are clean; no full suite was run,
per Victor's proportional-testing instruction. The parity fixture did not change.

All four obsolete worktrees were verified clean and merged before removal; their four local
branches were deleted and `git worktree prune` completed. The only remaining worktree is the main
Golden Vector tree on `dev-vic`. The main-branch merge remains deliberately paused for Victor's
Phase 1 release checkpoint, as required by the handoff.
