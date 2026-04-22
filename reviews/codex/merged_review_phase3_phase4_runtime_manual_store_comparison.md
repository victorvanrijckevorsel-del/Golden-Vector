# Merged Review Comparison: Phase 3 / Phase 4 Runtime, Manual Store, and Reliability Hardening

Date: 2026-04-22
Sources compared:
- [Codex self-review](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/codex_review_phase3_phase4_runtime_manual_store_findings.md)
- [Claude review](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/claude_review_phase3_phase4_runtime_manual_store_findings.md)

## High-Level Result

Both reviews agree on the same overall verdict:

- `READY WITH MINOR CHANGES`

The difference is mostly in depth:

- **Claude** focused more on confirming the redesign is real and works as intended.
- **Codex** found a few deeper lifecycle and operator-model issues in the new local-first/manual-store behavior.

## Comparison Table

| Topic | Codex | Claude | Agreement | My take |
|---|---|---|---|---|
| Local-first runtime is real | Confirmed | Confirmed | Full agreement | Not a problem |
| Combined is correctly de-scoped | Confirmed | Confirmed | Full agreement | Not a problem |
| SQLite schema separates notes from calculations | Confirmed implicitly but flagged timestamp gap | Confirmed strongly | Broad agreement | Structure is good, but metadata is still thin |
| FX staleness is now explicit | Confirmed improvement but found manifest invalidation gap | Confirmed improvement | Partial agreement | Fix still needed around snapshot invalidation after policy changes |
| Immutable run snapshots are safe | Confirmed | Confirmed strongly | Full agreement | Good design |
| Manual store still auto-initializes / auto-imports during normal use | **Found as P1** | Not flagged | Difference | Real issue, should be fixed |
| Snapshot manifest does not include QA-policy settings | **Found as P1** | Not flagged | Difference | Real issue, should be fixed |
| Manual-data CLI cannot clear values | **Found as P2** | Not flagged | Difference | Real issue for usability, should be fixed |
| CSV backup/migration path is incomplete because notes are excluded | **Found as P2** | Partially flagged via round-trip test gap | Partial overlap | Real issue, but smaller than the first three |
| CSV import/export round-trip test missing | Mentioned as part of backup/migration gap | **Found as P2** | Agreement in substance | Should add test |
| CSV export overwrites support files directly | Not flagged | **Found as P2** | Difference | Worth fixing, but lower priority than the P1 items |
| `codex-full-briefing.md` still reflects old product model | Not flagged in latest self-review | **Found as P2** | Difference | Documentation fix worth doing |
| NaN/NaT string literal leakage from corrupt CSVs | Not flagged | **Found as P2** | Difference | Low-risk edge case |
| Core manual-input tables lack edit timestamps | **Found as P2** | Not flagged | Difference | Worth fixing, but not before the P1 items |

## What Both Reviews Say Clearly

These points are now well established:

1. The runtime redesign was a real improvement.
2. `update-data` is now the only heavy refresh path.
3. `tool-a` and `tool-b` are genuinely local-first.
4. Combined is no longer an active backend engine.
5. The SQLite manual store is directionally the right replacement for CSV-first runtime behavior.
6. FX staleness and snapshot hardening improved the system meaningfully.

## What Claude Found That I Did Not Emphasize

### 1. Support CSV export can overwrite user-managed CSV files
- Claude is right that `export-csv` currently overwrites the support CSV files directly.
- This is a real operator-risk, though I still rank it below the lifecycle issues in the new runtime/store behavior.

### 2. `codex-full-briefing.md` is still stale
- Claude is right.
- This is not a runtime bug, but it does matter because that file is still presented as a must-read context document.

### 3. Missing explicit round-trip test
- Claude is right again.
- I treated that as part of the broader CSV backup/migration weakness; Claude separated it into a concrete test gap, which is useful.

## What I Found That Claude Did Not Flag

### 1. Snapshot invalidation is incomplete
- This is the most important gap still open.
- The whole local-first model depends on knowing whether the stored snapshot is still valid under the current policy.
- Right now that validity check is too narrow.

### 2. Normal Tool B usage still mutates local manual-data state
- This conflicts with the new product direction more than it may first appear.
- `manual-data init` is supposed to be meaningful, but the store currently auto-creates/imports on normal use paths.

### 3. The direct manual-data workflow still cannot clear values
- Now that direct in-tool editing is the primary workflow, this is not a nice-to-have.
- It is a real missing operator capability.

### 4. Manual input records still lack timestamps
- This is not blocking, but it weakens the usefulness of the new store as a long-term working tool.

## Final Merged Priority

If we act on both reviews together, I would fix things in this order:

1. **P1**: Expand latest-snapshot invalidation to include refresh-affecting QA policy.
2. **P1**: Make normal Tool B usage read-only with respect to store creation/import.
3. **P2**: Add clear/remove support to the new manual-data CLI.
4. **P2**: Add a CSV import -> store -> export round-trip test.
5. **P2**: Decide whether CSV is a real backup path or only partial compatibility support, then align docs and behavior.
6. **P2**: Prevent blind overwrite risk in `export-csv` or at least back up existing files.
7. **P2**: Add timestamps to core manual-input tables.
8. **P2**: Add a staleness note to `codex-full-briefing.md`.

## Bottom Line

The redesign is good and the core direction is right.

But the merged review says there are still **three real follow-up fixes** that matter more than the rest:

1. snapshot invalidation after QA-policy changes
2. hidden store mutation during normal Tool B use
3. no clear/remove path in the new direct-edit workflow

Everything else is secondary hardening or documentation cleanup.
