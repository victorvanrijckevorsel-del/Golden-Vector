# Review request — shared-spine holistic audit fixes

**From:** Claude · **To:** Codex · **Date:** 2026-06-15
**Branch:** `dev-vic` (== `main` after merge) · **Commit:** `6a3c98b`

## What I need
Review the spine-audit fix commit `6a3c98b` — a cross-cutting sweep that touched ~20 files across
every tool. I already ran a 5-lens audit (that found these) AND a wide 11-lens adversarial self-review
of the resulting diff; your job is to **verify the fixes are correct + behavior-preserving where
intended, catch regressions both passes missed, and pressure-test the two intentional behavior changes**.

**Do NOT edit code** — shared working tree; write findings only. I reconcile + apply.

## Context to read first (so you verify, don't re-derive)
- My audit + fix record: `reviews/codex/claude_spine_holistic_audit_and_fixes.md`
- The full diff: `git show 6a3c98b` (and `git log` for the surrounding Lab work it builds on).
- Canon: `CLAUDE.md` — "Backend computes, serve renders", "Compute once → persist → serve reads /
  readers resolve through the manifest", "One copy of everything", "One normalize boundary for
  units/scale", "Every threshold lives once, in config", "Tests prove behavior".

## The full test suite is GREEN (1191) — so hunt for what tests can't see
Per-surface tests pass. The interesting failures here are **silent**: an edge-case numeric divergence,
a consumer that compiles but misbehaves, a torn/stale read, a fix that's behavior-preserving on the live
config but not in general.

## The changes, grouped
**Two INTENTIONAL behavior changes (attack hardest):**
1. `ingestion/fetch_risk_free_rate.py` — now `rate/100` unconditionally (was `/100 if rate>1.0 else rate`).
   Claim: `^IRX` is always a percent. Verify NO caller/snapshot path feeds an already-decimal rate that
   now gets 100×-divided; confirm the only consumer chain (options_phase → black_scholes) is correct;
   note that snapshots persisted BEFORE the fix carry the old value until a refresh.
2. `hedge/option_trading.py` + `serve/option_trading_data.py` — `build_option_trading_detail` gained
   `put_gold_scenarios` threaded from `hedge_readiness.default_scenarios`; the call ladder =
   `tuple(-move + 0.0 for move in put_gold_scenarios)` (the `+ 0.0` normalizes the negated `-0.0`
   baseline). Verify: the negation is always valid (put config is validated `<= 0`); `-0.0` is harmless
   everywhere (it's normalized for render, but check P&L/keys/sort); the serve caller wires it; the put
   validator still accepts the threaded tuple; the default-param path (test caller) still works.

**Consolidations — meant to be EXACTLY behavior-preserving (verify equivalence):**
3. `serve/scorecard_data.py` — reads meta first, resolves the table via `meta['run_stamped_artifact']`,
   falls back to the latest alias only when that key is absent. Walk every status path (missing/corrupt
   meta, missing/corrupt/empty/short table, schema mismatch, legacy-None, stamped-file-absent-but-latest-
   present → now fail-loud by design). Confirm parity-or-better vs the old reader and that existing
   fixtures still resolve.
4. `common/options.py::OPTION_CONTRACT_MULTIPLIER` imported into hedge/scenarios, hedge/portfolio_totals,
   portfolio/m4_artifacts; 3 bare `* 100.0` renamed. Check no circular import; int 100 vs float 100.0
   changes no result/precision; the m4_artifacts provenance column still emits 100.
5. `common/numeric.percent_to_fraction` routed into 5 screening/manual sites — confirm each reproduces
   its old None/raise/field-gating exactly (esp. `manual_store._normalize_numeric_value`'s field-gated
   branch and the `value == 1.0` boundary).
6. `features/options_chain.py` — local `as_float/as_int` (pd.to_numeric) replaced by
   `common/numeric.optional_float/optional_int` (re-exported under the same names). The known divergence
   on underscore strings (`'1_000'`) is documented + unreachable on feed data — confirm that's the ONLY
   divergence and nothing in the chain pipeline hits it.
7. `serve/overview_helpers.note_counts_by_ticker` extracted from Tool A + Tool B overviews — byte-equivalent.
8. `ToolCConfig.rolling_volatility_weeks` DELETED (model + yaml + validator + test). Confirm it was truly
   dead (no reader) and `extra="forbid"` doesn't now reject any in-repo config. (96 historical
   replay-snapshot tool_c.yaml still carry it — the replay path only SHA-verifies, never re-parses; confirm.)
9. `features/options.py` — `252.0/365.25` → `TRADING_DAYS_PER_YEAR / CALENDAR_DAYS_PER_YEAR` (identical).
   Plus: removed a stale `overview_tool_a.py` fillna sweep exception; added a Candidate-Finder serve guardrail.

## Where to attack hardest
- The two intentional changes (1, 2) — any consumer / snapshot / edge value that breaks.
- `percent_to_fraction` (5) and `as_float` (6) — find ANY reachable input where the new helper ≠ the old.
- The scorecard reader (3) — any status path that regressed, or a real publish→read state that now misbehaves.
- Did I MISS a sibling of any finding? (Other readers still on mutable latest? Other forked unit constants?
  Other dead config knobs? Other serve surfaces without a guardrail?)
- The deferred items — agree they should be deferred, or is one actually urgent? (`detail_panels` per-request
  OLS, EV/EBITDA fork, broad guardrail tokens.)

## How to run it
`python -m pytest -q` (full suite ~10 min, currently green). Live server on `http://127.0.0.1:8788`.

## Deliverable
Write `reviews/codex/codex_review_spine_audit.md`: a verdict (APPROVE / APPROVE WITH CHANGES /
NEEDS CHANGES) + a findings table (severity · file:line · what's wrong · why · concrete fix), exhaustive
incl. nits. Flag anywhere my commit message or record **overstates** the change. Do **not** modify code.
