# I5 Gate Review — Foundation Cleanup (commit eddc67d)

**Reviewer:** Claude Code (Opus 4.8)
**HEAD:** `eddc67d` (clean tree). Reviewed the alignment consolidation first-hand + three parallel deep-dives (consolidation behavior, numeric/throttle/attrs fixes, suite+regression); full suite executed.
**Grade: PASS — with one gap to close (test coverage for the consolidation).** All five I5 follow-ups from `claude_review_foundation_holistic.md` + `claude_review_i4_gate.md` are genuinely done, including the two hardest (the 6-way alignment consolidation and the parquet-attrs fragility fix). **752 tests pass, no regression-masking.** The only real gap is that the consolidation — whose entire purpose is "one freshness answer everywhere" — shipped under-tested.

---

## 1. Alignment consolidation (the #1 item) — PASS, genuinely done
This was the highest-stakes change (it alters warnings on four screens). Codex did it the right way, not a blind swap:
- **A single shared source of truth** now exists: `summarize_model_state_alignment` (`model_state.py:291-326`) reads the manifest's authoritative `_alignment` block, with thoughtful guards — no manifest → returns `None` so legacy callers fall back; OK-but-`state != complete` → `None` so it never falsely reports "fresh" on a half-built manifest; unreadable → `UNKNOWN`.
- **All four consumers wired to it** (I verified the Finder merge first-hand at `candidate_finder_data.py:570-612`):
  - **CLI status** (`cli.py:3034`) — manifest primary, old logic fallback-only.
  - **Candidate Finder** — manifest verdict first, then its **manual-store-freshness** extra appended + deduped (`_dedupe_alignment_messages`). Old run-id recompute is fallback-only. Clean additive merge.
  - **Hedge report** (`report.py:1264`) — manifest verdict replaces the old tool-a/b-vs-options check (which becomes fallback-only).
  - **Option Trading** — the subtle one, and **done correctly**: the option page warnings used to be *baked into the artifact at build time* (`_context_warnings`), so they couldn't reflect a later standalone tool-c rerun. Now the **serve path reads the manifest at display time** (`option_trading_data.py:404`, `_with_model_state_alignment_warnings`) and prepends the manifest warnings onto the rendered banner, while keeping the baked-in context warning additively.
- **The divergence is resolved.** In the canonical failure case — *rerun `tool-c` standalone after a refresh* — all four screens now surface the **same** tool-c mismatch (CLI MISMATCH, Finder WARN, option-page banner, report WARN). That's the exact inconsistency the foundation review flagged, and it's closed.
- **My foundation review's key caveat was honored:** scope was reconciled (manifest verdict as the base, each screen's extras preserved as additive notes), not a blind swap that loses the Finder's manual-store check or double-warns.
- **No crash path** for a missing/old-shaped manifest — every field is `.get()`/`isinstance`-guarded and coerced to `UNKNOWN`/`None`; the option cache key includes the manifest hash so a tool-c rerun busts the cache.

## 2. The other four follow-ups — all FIXED
- **`common/numeric.py`** (real consolidation): ~13 local copies of `_optional_float`/`_numeric`/`_int_value`/`_event_int`/`_as_float` removed and routed through the shared helper. Behavior preserved by splitting `optional_float` (None-on-invalid) vs `strict_optional_float` (raise-on-invalid) — the two call sites that *raised* (`pipeline.py`, `structural.py`) correctly use the strict variant. (Two unrelated lineages — `features/options_chain.as_float/as_int` and `option_refresh._optional_int` — remain, but were outside this finding's scope.)
- **Configurable Yahoo retry/throttle** (the I4-gate finding): `config/market_data.yaml` with a **non-zero `yahoo_throttle_seconds: 0.15`** (the "throttle effectively off" problem is resolved), genuinely wired into the live `YahooClient` via `retry_policy_from_config` in `foundation.py`/`options_phase.py`, validated + tested. So your refresh will now space out Yahoo calls slightly, and you can tune it in YAML.
- **Parquet attrs fragility** (foundation finding #3): a **real fix** — schema/run metadata is now written into the **Parquet file's key-value schema metadata** (`_write_parquet_with_metadata`, a guaranteed parquet feature) and read back into `attrs`, so empty-frame schema validation no longer depends on pandas `DataFrame.attrs` surviving a round-trip. Tested with an explicit empty-frame round-trip.
- **`prune-runs` comment** added.

## 3. Suite + regressions — clean
**752 passed, 0 failed, 0 skipped, 0 xfail.** No tests deleted, no skips. The one loosened assertion (`test_option_trading_data.py:135` changed `context_warnings[0]` → `any(...)`) is **benign and verified** — the correct warning is still produced; it's defensive future-proofing for when a manifest warning legitimately prepends. The numeric and throttle consolidations weakened no existing assertions (they added new tests).

## The one gap to close — test coverage for the consolidation
Both the behavior review and the regression audit independently flagged this, and I agree it's the one real shortfall: **the consolidation is correct but under-tested.**
- **No direct unit test** for `summarize_model_state_alignment` itself (its `state != complete → None` and `manifest_readable is False → UNKNOWN` branches are untested).
- **No cross-screen-consistency test** — the *entire point* of this milestone is "one freshness answer on every screen," yet nothing asserts that CLI status, Finder, option page, and report produce the **same** verdict from one manifest. Without it, a future change to one screen's wiring could silently re-introduce the divergence and no test would catch it.
- Only the **Candidate Finder** got a new manifest-driven test; **CLI status and the hedge report alignment changes shipped with no test coverage at all.**

**Recommendation (small, before calling I5 fully closed):** add (a) unit tests for `summarize_model_state_alignment` (the OK/WARN/UNKNOWN/None branches), and (b) one cross-screen-consistency test that builds a manifest with a tool-c mismatch and asserts all four surfaces report it. That locks in the invariant this milestone was built to create.

## Bottom line
**I5 passes — and this was the last milestone, so the I1→I5 data-architecture remediation is now built.** The cleanup genuinely closed every follow-up, including the hard alignment consolidation (done thoughtfully, divergence resolved) and the attrs fix. The foundation is solid *and* now clean. The single thing I'd ask for is the alignment test coverage above — it's the guardrail that keeps the "one freshness answer" invariant from silently breaking later. After that, the only thing left is operational: **run a full refresh** to put real data on this finished foundation.
