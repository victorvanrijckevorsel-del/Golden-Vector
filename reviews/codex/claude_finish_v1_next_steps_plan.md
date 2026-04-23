# Golden Vector V1 Finish Plan For Claude

Date: 2026-04-23  
Purpose: give Claude a clear, practical plan for the remaining work needed to finish the tool as a usable v1 product.

## 1. Current Project State

Golden Vector is no longer in “build the engine from scratch” mode.

The main engine is already built:

- `update-data` is the explicit market-data refresh step
- Tool A is now the official structural model
- Tool B runs from the local validated snapshot plus the SQLite manual-data store
- `workspace` is the current product surface
- the heavy Combined backend is removed from the active product
- the future compare view is intentionally deferred

The repo is now in the state:

- backend mostly built
- main analytical flows working
- tests strong
- major FX / normalization mistakes already reduced
- remaining work is mostly about making the product surface complete, trustworthy, and easy to use

## 2. What Is Already Built

### Core engine
- market-data refresh pipeline
- USD normalization layer
- raw QA and normalization QA
- Tool A structural model
- Tool B screening model
- local latest-artifact runtime

### Tool A
- structural delta
- gamma / regime split
- asymmetry
- confidence
- volatility diagnostics
- explanation fields

### Tool B
- SQLite manual-data store
- direct CLI editing
- notes/comments per stock
- import/export compatibility path for support CSVs

### Workspace
- overview page
- stock detail page
- Tool B company-input editing
- reporting-calendar editing
- stock notes
- Tool A explanation display
- latest Tool A / Tool B display

## 3. What Is Not Finished Yet

The tool is not fully “done” because the product shell is still thinner than the engine underneath it.

Main unfinished areas:

1. workspace completion
2. final workflow polish
3. final release hardening
4. compare view at the very end

## 4. The Next Best Step

## Finish the workspace

This should be the next major milestone.

The reason is simple:

- the backend is already strong enough to use
- the missing part is the day-to-day product experience
- if the workspace becomes complete, the tool starts to feel finished

## 5. Workspace Completion Scope

Claude should treat this as the next main milestone.

### 5.1 Source-verification editing in the workspace

Right now source verification is visible, but not editable directly in the UI.

Build:
- ability to edit verification status
- source date
- source URL
- notes

For each Tool B field, the user should be able to maintain the verification record without dropping to the CLI.

### 5.2 Better Tool B manual-data workflow in the workspace

Improve:
- visibility of missing required fields
- visibility of verified vs estimated vs incomplete fields
- clearer edit/save feedback
- explicit “clear value” behavior if useful

Goal:
- a normal Tool B maintenance workflow should happen in the workspace, not in the CLI

### 5.3 Better notes handling

Improve:
- note display
- note status/tag readability
- browsing of notes per stock

Do not overbuild this. Just make it comfortable and clear.

### 5.4 Overview table usability

Add basic browsing tools:
- search by ticker
- filter by Tool A profile if useful
- filter by Tool B verdict
- filter by confidence if useful
- sort by ticker / Tool A rank / Tool B rank

Keep this lightweight. No need for a complex frontend framework.

### 5.5 Snapshot freshness and provenance display

The workspace should clearly show:
- latest foundation refresh id
- snapshot as-of date
- latest Tool A refresh linkage
- latest Tool B refresh linkage
- clear warnings if outputs are stale, missing, or mismatched

This is critical for trust.

## 6. After Workspace Completion

## Final workflow polish

Once the workspace is complete enough, do one smaller pass focused on operator trust and usability.

### 6.1 Better empty states and warnings

No silent blanks.

The user should see clear messages when:
- latest Tool A output is missing
- latest Tool B output is missing
- outputs are out of sync with the current refresh
- manual store is missing
- required Tool B inputs are incomplete

### 6.2 Smooth refresh/use workflow

The normal user workflow should be:

1. `python main.py update-data`
2. `python main.py tool-a`
3. `python main.py tool-b --gold-price 4000`
4. `python main.py workspace`

The workspace should make this feel obvious and coherent.

### 6.3 Minor export / inspection support only if useful

Do not reintroduce CSV-first workflows.

CSV stays secondary.

Only improve export/inspection if it clearly helps the user understand or audit the current state.

## 7. Final Release Hardening

After the workspace milestone and workflow polish, do one final v1 hardening pass.

### 7.1 Full repo review
- one more holistic review
- findings first
- fix any remaining real issues immediately

### 7.2 Live smoke checks
Run and verify:
- `python main.py update-data`
- `python main.py tool-a`
- `python main.py manual-data init`
- `python main.py tool-b --gold-price 4000`
- `python main.py workspace`

### 7.3 Docs cleanup
Make sure:
- README matches the real workflow
- architecture map matches the repo
- no stale guidance remains in the main operator docs

### 7.4 Final trust bar
The tool should feel:
- explicit
- local-first
- auditable
- understandable

## 8. Compare View Must Stay Deferred

Do **not** build the compare view yet.

That should stay as the final product layer after:
- Tool A is comfortable to inspect
- Tool B is comfortable to maintain
- the workspace is already a solid day-to-day tool

When it is eventually built, it should be:
- a side-by-side view only
- not a new backend engine
- not a return of the old Combined pipeline

## 9. Recommended Execution Order

Claude should follow this order:

1. finish workspace editing and browsing
2. polish refresh/provenance/empty-state behavior
3. do final hardening and docs cleanup
4. stop there unless asked to build the compare view

## 10. Acceptance Criteria For “Finished Enough For V1”

The tool should count as “finished enough” when:

- Tool A and Tool B both run cleanly from local data
- the workspace is the normal day-to-day interface
- Tool B manual data can be maintained comfortably in the workspace
- Tool A outputs are clearly explained and easy to inspect
- provenance / freshness / mismatch warnings are clear
- no major hidden side effects remain
- tests are green
- final live smoke checks pass

## 11. Practical Guidance For Claude

When implementing this next phase:

- prioritize clarity over cleverness
- prefer simple server-rendered improvements over big frontend complexity
- keep FX / normalization trust visible
- do not add a heavy compare backend
- do not broaden Tool A or Tool B conceptually unless there is a strong reason
- focus on finishing the product surface, not inventing new backend layers

## 12. Short Version

If you only keep one summary in mind, keep this:

**The engine is mostly built. The next job is to finish the workspace so the product feels complete, trustworthy, and easy to use. Then do one final hardening pass. The compare view comes last.**
