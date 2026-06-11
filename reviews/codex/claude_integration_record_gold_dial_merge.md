# Integration Record — m1-gold-dial × option carry-forward/B/D1 (2026-06-11)

Executed by Claude per `codex_safe_merge_handoff_gold_dial_vs_option_work.md`, with plan
amendments. Result: **integrated into `dev-vic` at `98dbc62`**, 995 tests green, ruff clean.
`main` intentionally NOT updated yet — pending the real-refresh smoke test (calls Yahoo;
needs Emanuel's go).

## What was done (sequence)

1. **Secure first (plan amendment):** committed the 9 staged verification-fix files +2 review
   docs in the worktree (`8ac6216`) and pushed `m1-gold-dial` to origin BEFORE any merge —
   work loss became impossible. (The stale remote previously held only PR1/PR2.)
2. **Baseline:** branch tip green on its focused suites (75 tests) before merging.
3. **Measured the true overlap (plan amendment):** files changed on BOTH sides since the
   `db5cfbc` merge-base = **5** (`model_state.py`, `cli.py`, `candidate_finder_page.py`,
   `workspace.py`, `test_cli_refresh_and_status.py`) — not the ~25 in the handoff's
   high-risk-area list. Focus went there.
4. **Merge:** `integration/gold-dial-after-option-d1` from `main`, merged local
   `m1-gold-dial` (`2f0f899`). **Zero textual conflicts** — treated as suspect, not success.
5. **Tests:** main-side suites 50/50, gold-dial suites 162/162, full suite 990/990, ruff clean.
6. **Adversarial verification:** 8 surface auditors launched; 4 completed (Candidate Finder,
   Option UI, Tool D/portfolio, cross-feature) before a session limit killed the other 4
   (model-state, refresh-cli, tool-b, fundamentals-store). The 4 missing surfaces were
   completed manually by Claude (first-hand reads; model-state and refresh-cli had already
   been hand-verified during the merge).
7. **Two HIGH semantic bugs found and fixed (`98dbc62`)** — see below.
8. Merged integration → `dev-vic`, pushed.

## The two semantic bugs (invisible to all 990 tests)

### HIGH-1 — CF scenario ignored official fundamentals
`_compute_scenario_sources` called `compute_tool_b_in_memory` **without**
`official_fundamentals`, while the persisted pipeline (`screening/pipeline.py:68,80`) and the
Tool B dial (`overview_tool_b.py:417,441`) both pass it. Via `resolution.py:81-88`, tickers
whose net debt / EBITDA / D&A / interest exist only in the official store lost
leverage/EV-EBITDA/forward-PE under any scenario — **even at exactly spot** — silently
dropping them from eligible ranking. Both scenario tests mocked `compute_tool_b_in_memory`,
so no test could catch it.
**Fix:** thread `load_official_fundamentals(paths)` into the scenario compute; add the
officials file hash to the scenario cache key; regression test asserts the kwarg is passed.
**Deliberate non-change:** Tool D's internal Tool B legs stay manual-only — they are
manual-only on BOTH the persisted and scenario sides (consistent basis). Threading officials
into Tool D everywhere is a gold-dial follow-up, not a merge fix.

### HIGH-2 — Non-option publishers broke the carried-forward window
Pre-existing Milestone A gap, amplified by the merge adding a publisher: portfolio lot
add/edit/delete (workspace → `build_portfolio_artifacts(publish_model_state=True)`),
`fetch-fundamentals` (`publish_current=True`), and `refresh --skip-tool-b` all call
`write_current_model_state_manifest` **without** `option_publish_block`. During a
carried-forward window that republished the option domain as "OK" (dishonest — aliases still
hold the old snapshot) and resurrected run-id mismatch warnings (state → incomplete, calm
consumers broken).
**Fix at the shared seam** so every publisher inherits at once:
`_inherited_option_publish_block` in `build_current_model_state_manifest` — when no block is
passed and the previous manifest's option domain is CARRIED_FORWARD/UNAVAILABLE, the previous
block is inherited **unless** a fresh option build aligned with the current options ingestion
manifest exists on disk (then OK is truthful). 3 regression tests (inherit-carried,
return-to-OK-after-fresh-build, inherit-unavailable).

## Smaller findings handled

- Scenario screens no longer show the misleading manual-store freshness warning (scenario
  always computes from the live store) — LOW from verifier 3.
- Parametrized guard test: every `COLUMN_HELP` thresholds callable resolves against the real
  config (prevents silent tooltip degradation) — NIT from verifier 6.

## Deferred (recorded, deliberately not done now)

| Item | Severity | Why deferred |
|---|---|---|
| CF legacy alignment fallback can mention option ids when manifest is OK-but-incomplete | LOW | Only reachable when something *else* is already broken; warnings then arguably appropriate |
| Shared LRU between default+scenario cache entries (eviction pressure, no correctness issue) | NIT | Keys are airtight; cosmetic capacity tuning |
| "Signal" header vs "Option Signal" filter label naming + COLUMN_HELP entry for direction | NIT | Pre-existing D1 cosmetic, not merge drift |
| Surface fundamentals staleness line on Tool B page header | NIT | UX polish for the gold-dial follow-up |
| Thread officials into Tool D's three Tool B legs (persisted + scenario together) | FOLLOW-UP | Must change both sides at once to keep bases consistent |

## Codex's 6 handoff questions — answers as implemented

1. Freshness domains stay in `model_state.py` (now with the publisher-inheritance seam).
2. `fetch-fundamentals` stays a **separate command** — the branch itself had not wired it into
   `refresh`; sequencing decision deferred until first successful official-data refresh.
3. Carried options + degraded fundamentals in one run: both visible — freshness domain says
   CARRIED_FORWARD; fundamentals staleness is an informational warning; verified it can never
   flip state to incomplete (`_is_required_health_warning` audit).
4. Scenario Finder + carried option fields: allowed; the carried-forward note renders in
   scenario mode too (freshness box is manifest-driven, cache key includes manifest hash).
5. Market-vs-Ours first home: `/tool-b` only (as PR6 built it).
6. Integration branch + single merge of local branch — done; cherry-pick fallback not needed.

## Remaining before `main`

1. **Smoke test (needs Emanuel):** `python main.py refresh` (calls Yahoo) + workspace UI pass:
   `/`, `/tool-b` (dial + Market-vs-Ours), `/tool-d`, `/option-trading` (freshness box,
   column help), `/ticker/AEM?lens=option-trading`, Candidate Finder (Bull/Bear, Universe,
   scenario at spot vs default equality).
2. Then merge `dev-vic` → `main` per the milestone workflow; only after a successful smoke,
   delete `m1-gold-dial` + the integration branch.
