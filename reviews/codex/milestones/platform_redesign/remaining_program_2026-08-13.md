# Platform redesign: remaining implementation program — 2026-08-13

Baseline: `1df7f11` (`fix: complementary review of Phases 1-4 — 27 verified findings`).
Claude's complementary review is accepted as the Phase 1–4 closure; this program does not repeat
the same review lenses.

## Victor's added product decisions

1. Ticker Lab controls use the shared segmented control. Eight weeks remains the pre-declared
   default; it must not change opportunistically to whichever horizon makes a stock look best.
2. The ticker explains persisted gold-move behaviour in plain English: capture versus gold/GDX,
   standing versus miners, and recent independent episodes versus older history.
3. The historical large-fall panel separates frequency from severity (median decline as the main
   severity measure, worst event as context), compares the stock with GDX and the eligible-miner
   median, and shows a configured two-year recent view beside full history. Thin recent evidence is
   described as thin rather than over-interpreted. Existing ranking inputs stay unchanged.
4. Candidate Finder hides redundant displayed ranking percentiles in both list modes. Internal
   percentiles, scores, ordering, and a genuine user-selected `IV percentile` metric remain intact.
5. A portable refresh coordinator runs the existing coherent refresh independently of the web UI:
   once after first startup/sign-in/resume each day, and once after 5:00 PM New York on trading
   days. Windows Task Scheduler is only an adapter; the coordinator remains cloud-runnable.
   Automatic runs are hidden, use the existing single-writer guard, wake from sleep where Windows
   and firmware permit, and retry failures after 15/30/60 minutes.
6. Options always show the latest valid complete snapshot per ticker. A failed ticker may retain its
   prior verified snapshot while successful tickers advance; contracts from different snapshots
   are never mixed within one ticker. `NONE_LISTED` is authoritative and does not resurrect old
   contracts. Every row carries its source run/date/capture provenance. Copy says “Latest available”,
   with discreet Eastern-time context; three or more US trading days old gets a stronger warning.
7. A small global status reports the last successful atomic model publication and any running or
   failed attempt without scattering timestamps through every section.

## Remaining delivery order

1. Interpretation/UI reuse and Candidate Finder cleanup (focused tests).
2. Versioned downside-context producer/artifact/reader/UI (contract tests, then affected suites).
3. Portable scheduler, Windows XML adapter, retry state, and global status (no task installed during
   automated tests).
4. Versioned per-ticker options provenance and carry-forward (focused fault-injection and reader
   tests; keep whole-generation outage fallback).
5. Phase 5 platform rollout in the locked page order: Tool B, Tool D, Candidate Finder, Tool A,
   Tool C, Option Trading, Portfolio, Lab, Scorecard. Resolve the named carryovers at each owning
   page: Tool-A query state, resilience wording, series-control/legend merge, duplicate identity,
   legacy presentation selectors.
6. Persist the five deferred gold-response spot metrics and remove the false JavaScript-only spot
   placeholders.
7. Phase 6: integration/branch audit, static and focused gates, one full suite, one real coherent
   refresh, manifest/replay checks, request-path computation scan, performance comparison, and one
   batched browser/accessibility/visual pass before release.

## Review and testing policy

- Use focused tests while a lane is changing; the full suite is reserved for versioned-contract
  integration gates and final release.
- Reviews are complementary: producer/reader seams, realistic failure states, and real persisted
  generations. Do not re-run already-closed synthetic edge matrices without a changed contract.
- No automatic task is installed and no live API refresh is invoked without the separately required
  operating-system/API authority. Tests inspect generated task definitions and coordinator decisions.
- Every new analytical value is computed once, persisted as a versioned artifact, resolved through
  the current-state manifest, and only formatted in the serve layer.

