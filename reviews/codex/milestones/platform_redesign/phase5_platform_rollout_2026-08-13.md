# Phase 5 platform rollout — implementation record

Baseline: `1df7f11` (`fix: complementary review of Phases 1-4 — 27 verified findings`).

## Outcome

The ticker reference design now extends across Tool B, Tool D, Candidate Finder, Tool A, Tool C,
Option Trading, Portfolio, Lab, and Scorecard. The rollout reused the shared components instead of
creating page-local design systems, and preserved each page's analytical and source contracts.

## Product additions folded into the rollout

- Ticker Lab uses the shared horizon/benchmark controls, defaults honestly to the configured 8-week
  view, and presents persisted capture, peer standing, and recent-versus-older interpretation.
- Historical large-fall context now separates frequency from severity, adds full-history and
  configured two-year views, and compares stock/GDX with a clearly qualified eligible-miner median.
- Candidate Finder no longer displays redundant ranking-percentile columns. Raw criterion values,
  scores, ordering, and the genuine selectable IV-percentile metric remain.
- Options publish latest-valid provenance per ticker. A failed ticker can retain one previously
  verified whole-ticker snapshot while successful tickers advance; `NONE_LISTED` remains
  authoritative. The effective fresh-plus-stored cohort is ranked together, and the UI gives one
  discreet Eastern-time context plus a strong warning at three trading days.
- A portable unattended-refresh coordinator, hidden Windows Task Scheduler adapter, and small global
  data-status indicator were added. The former fixed-name visible-console tasks are removed during
  installation. A local daily rollover trigger prevents an always-on computer from missing the next
  day, and an independent 15-minute heartbeat keeps the 15/30/60 retries available after a long run.
- Global status follows a dedicated full-data-refresh timestamp. Portfolio edits and standalone
  fundamentals publication can republish the atomic manifest without falsely making market data
  look newer or satisfying a scheduled refresh slot.
- A complete Options-provider outage is nonfatal to the other datasets: verified ticker bundles are
  retained, unverifiable tickers are explicitly unavailable, and derived Options artifacts remain
  clearly carried or unavailable rather than being advertised as fresh.

## Shared-system closure

- All production `_metric_card`/legacy `metric-card` consumers were migrated to `data_card`.
- `.button-like` and other zero-consumer compatibility selectors were removed.
- The shared content width and sidebar width are tokenized; the last ordinary bare action uses the
  shared `control`. The sidebar deliberately remains 15rem to keep real navigation labels readable.
- Repeated Financials-source controls use the same visible label, option names, source semantics, and
  selected-state treatment.
- Empty, missing, stale, and corrupt states use explicit presentation instead of analytical-looking
  empty results.

## Focused verification during implementation

Focused suites were used at each ownership boundary rather than repeatedly running the full suite:

- Tool B / Tool D / Candidate Finder: 33 page tests, 6 Tool D tests, 15 route/table tests, then 28
  Candidate Finder tests and 13 route/workspace tests.
- Tool A / Tool C: 9 route tests, 8 window tests, and 84 shared/DataTables tests.
- Portfolio / Scorecard: 52 focused tests and 9 route tests.
- Lab / ticker interpretation: 107 Lab tests and 74 interpretation/Finder tests.
- Scheduler/global status: focused scheduler tests plus a 312-test integration batch; its two then-
  failing design assertions were caused by in-progress selector cleanup and were subsequently fixed.
- Options provenance/carry-forward: the last fully executed focused batches totalled 219 passing
  tests. A final mixed-cohort percentile regression was then added after identifying and fixing the
  fresh-versus-stored ranking seam; the environment test-execution quota blocked only that final
  rerun, so it remains part of the release gate rather than being claimed green here.
- Shared source-label integration: 169 tests passed. Global-default/design cleanup: 41 tests passed.
- Gold-response v2 JavaScript/version seam: 71 tests passed.

The final focused selection, full suite, coherent refresh, and browser evidence belong to the Phase 6
release record and are intentionally not duplicated here.
