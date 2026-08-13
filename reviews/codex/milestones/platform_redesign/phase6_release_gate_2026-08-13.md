# Phase 6 release gate — 2026-08-13

## Implementation status

The requested application work is implemented in the `dev-vic` working tree:

- the professional shared design is rolled across the ticker, Tool A/B/C/D, Candidate Finder,
  Option Trading, Portfolio, Lab, and Scorecard;
- ticker gold-behaviour controls and persisted interpretation are clearer, with 8 weeks retained
  as the declared default;
- the large-fall record separates frequency and severity, compares stock/GDX/eligible miners, and
  shows recent two-year evidence beside full history;
- redundant Candidate Finder ranking-percentile columns are hidden without changing ranking;
- the gold dial preserves true persisted spot values and both finance sources remain supported;
- background refresh has first-open, daily rollover, post-close, and durable retry-heartbeat
  triggers, uses the existing single-writer refresh, and runs through hidden `pythonw.exe` tasks;
- the global status follows the last successful **full data refresh**, so a portfolio edit cannot
  falsely make market data look newer;
- Options use per-ticker immutable provenance and latest-valid whole-ticker carry-forward. A total
  Options-provider outage no longer discards other datasets that refreshed successfully, and
  current `NONE_LISTED` evidence is distinguished from older stored evidence.

## Completed verification

- Focused suites were run throughout each ownership lane; their exact counts are recorded in
  `phase5_platform_rollout_2026-08-13.md`.
- The final static gate passes:
  - Ruff check across `golden_vector` and `tests`;
  - JavaScript syntax checks for the dial, shell, performance-series, and overlay scripts;
  - `git diff --check`;
  - no merge-conflict markers;
  - no remaining production legacy presentation selectors targeted by the rollout.
- The branch/worktree integration audit is recorded in
  `phase6_integration_audit_2026-08-13.md`.
- The request-path and diagnostic performance audit is recorded in
  `phase6_performance_request_audit_2026-08-13.md`.

## Gates awaiting executable/system authority

The environment rejected new Python processes after the last code fixes because its execution-
approval quota was exhausted. It separately rejected local application navigation in the in-app
browser. Therefore the following are deliberately **not** claimed complete yet:

1. the updated focused release selection (now including every changed Options, ticker, scheduler,
   status, replay, and downside contract suite);
2. one full pytest run;
3. one real coherent refresh against the configured free data sources, followed by manifest,
   replay, artifact-state, and naturally cached route checks;
4. one batched 1440/1024/390 visual and accessibility pass against that generation;
5. installation of the three hidden Windows scheduled tasks;
6. final fetch, commit/push, and the repository's required `dev-vic` → `main` integration workflow.

No code is staged or committed while those gates remain unverified. The unrelated untracked
`naukri.md` remains excluded.

## Final commands once authority is available

Run, in order, without repeating the earlier lane-by-lane suites:

1. `python tests/tools/run_focused_selection.py -q`
2. `python -m pytest -q`
3. `python main.py refresh`
4. manifest/replay/state and five-request ticker performance smoke
5. one browser matrix and accessibility scan
6. `python main.py install-scheduled-refresh-tasks --apply` from an elevated Windows context
7. refresh remote refs, repeat the integration inventory, stage everything except `naukri.md`,
   commit/push `dev-vic`, merge/push `main`, delete/recreate remote `dev-vic` per repository policy.
