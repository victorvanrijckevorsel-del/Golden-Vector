# Phase 0 exit-gate record — visual redesign baseline (2026-08-10)

Base commit `6c5015d`; Phase 0 work committed as `bae74c3` (plan corrections + Codex decisions) and `902369a` (characterization tests + contract matrix + defect register), with this record and the browser evidence completing the phase.

## Gate checklist

| Gate item | Status | Evidence |
|---|---|---|
| Plan approved and corrected | DONE | Plan §27 correction record; verdict APPROVE; Codex Q1-Q5 decisions applied |
| Branch/worktree situation understood | DONE | `dev-vic` == `origin/dev-vic`; `origin/main` synchronized at base; `origin/codex-source-mode` fully merged; single worktree; no overlapping unmerged work; `naukri.md` intentionally untracked and preserved |
| Focused baseline green | DONE | `python tests/tools/run_focused_selection.py -q` — result recorded below |
| Baseline artifacts stored, no private data | DONE | This directory: `audit_dossier.md`, `defect_register.md` (D1-D11), `baseline_contracts.json` (31 fixture-app route contracts), `route_timings_before.json`, `browser_measurements_before.json` (15 real routes × 6 viewports), `screenshots_before/` (14 curated shots, **no Portfolio content**), `artifact_hashes_before.json` + `artifact_hashes_after_check.json` |
| Machine-readable contracts + artifact hashes recorded | DONE | `baseline_contracts.json`; 1,871 persisted files hashed |
| Read-only rendering proven | DONE | After the full browser matrix + timing sweep against the live workspace: **0 changed, 0 missing, 0 added** of 1,871 hashed artifacts |
| No implementation conflict with other active work | DONE | Branch inventory above |
| Missing pre-migration route coverage added | DONE | `tests/test_redesign_routes.py`: first WSGI coverage for `/scorecard`, reporting POST (incl. blank-clears semantics), Portfolio lot edit/delete, unknown ticker/action, and the no-405/no-HEAD method-mismatch matrix — 21 tests green |
| Focused selection pinned | DONE | `tests/tools/run_focused_selection.py` (file-path based; no pytest markers exist; run from repo root) |
| WSGI helper consolidated | DONE | `tests/helpers.py::call_wsgi_app`; new tests use it (five legacy per-file copies remain for their own files, migration not forced) |
| Defect register created | DONE | D1-D11 with severity/cause/deferral/fix/regression fields per Codex requirement |

## Key baseline numbers (before any change)

- **Repository-wide collection:** 1,555 tests (`pytest --collect-only -q`), matching the plan exactly.
- **Warm route timings (median of 5, local):** `/` 340 ms · `/tool-a` 123 ms · `/tool-b` 162 ms · `/tool-c` 147 ms · `/tool-d` 238 ms · `/option-trading` 458 ms · `/portfolio` 700 ms · `/lab` 104 ms · `/scorecard` 33 ms · `/ticker/NEM` **3,261 ms** · `/ticker/NEM?lens=option-trading` **3,808 ms**. The ticker-detail pages are already an order of magnitude slower than every other route — pre-existing, recorded as the comparison base for §19.1.
- **Page-level horizontal overflow at 1,280 px:** tool-b 1,156 px · tool-d 1,932 px · portfolio 2,052 px · option-trading 231 px · tool-c 141 px · tool-a 19 px. At 390 px: portfolio 2,942 px · tool-d 2,822 px · tool-b 2,046 px · option-trading 1,121 px · tool-c 1,031 px · tool-a 909 px · lab 587 px · ticker 404 px. Candidate Finder, Lab dial, and Scorecard have zero overflow at every width.
- **Mobile navigation height:** 333 px at 390 px viewport (379 px at 320 px) before content begins — the plan's claim verified on the live product.
- **Real Portfolio page:** 17 tables / 25 forms / 22 disclosures — the plan's counts confirmed against live data (and recorded as data-dependent).
- **External requests during the full sweep: zero.** Page errors: zero. Console errors: only the expected 404 document fetch on the `/combined` error-page check.
- **New defect found by the browser matrix:** D11 — the Portfolio positions DataTable throws a blocking `alert()` on every real-browser load (column-model mismatch from nested lots tables; table has no `id`). Never caught before because no test executes JavaScript.
- **New defect found by characterization tests:** D1 upgraded — with Tool A artifacts present (every real ticker), all four ticker-form validation-error branches crash to the generic **500** page (`app_config=None` → `AttributeError` in `build_delta_explanation`); the previously-documented degraded 400 renders only in artifact-less fixtures. Existing 400 tests passed for the wrong reason.

## Focused baseline selection result

Command: `python tests/tools/run_focused_selection.py -q` (46 files) — **762 passed, 0 failed, in 13:19**. This 762-test selection supersedes the plan's earlier 371-test reference run as the pinned baseline; page-specific subsets are used during development, this full selection at batch gates.

## Notes for later phases

- Browser measurement/screenshot scripts suppress `window.alert` via init script (required until D11 is fixed) — keep that in the Phase 3/6/8 matrix runs and assert the captured alert list instead.
- The `/portfolio` real page is measured but never screenshotted; Portfolio visual evidence uses fixture data only.
- Phase 8 re-runs: `redesign_baseline_contracts.py --out .../contracts_after.json`, the timing script, the measurement matrix, and the hash comparison, then diffs against these files.
