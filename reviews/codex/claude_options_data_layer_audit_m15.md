# Options Data-Layer Audit — Hedge Readiness (M1.5)

**Reviewer:** Claude Code (Opus 4.8), read-only audit while Codex codes Batch 3
**Date:** 2026-06-02
**Scope:** the data foundation the whole put/call tool stands on — `features/options_chain.py` (normalization, tradability gates, delta, straddle implied move), `features/options.py` (feature row + optionability tier), `hedge/candidate_puts.py` (candidate selection). These are committed and **not** being edited by Codex, so findings are stable.
**Why this layer:** every candidate, scenario, ranking P&L, comparison row, and optionability label is derived from here. A defect here is invisible to the fixture tests and silently corrupts everything downstream.

---

## D-1 (HIGH — operational fragility, universe-wide blast radius) — A failed risk-free-rate fetch silently empties the entire tool, not just mispriced it

**The chain of events:**
1. `add_black_scholes_delta` (`options_chain.py:100-102`) returns **`delta = None` for every row** when `risk_free_rate is None`:
   ```python
   if risk_free_rate is None:
       result["delta"] = None
       return result
   ```
2. `strike_for_target_delta` (`black_scholes.py:96-99`) then filters to rows with a non-null delta — which is now **none of them** — and returns `None`.
3. `build_candidate_put_grid` (`candidate_puts.py:91-97`) gets `None` for every horizon → **no candidates for any ticker.**
4. In ingestion, `compute_options_features` derives `put_iv_25d_{h}d` from the same delta-matched selection, so `optionability_tier` (`options.py:222-228`) falls to **"thin" or "none" for the whole universe** (it needs `put_iv_25d` present at all horizons to be `directly_hedgeable`).

**Net effect:** on any day the `^IRX` fetch hiccups (which `options_phase._fetch_risk_free_rate` already treats as a non-fatal `None`), the report comes back **blank**: zero candidates, zero directly-hedgeable names, empty speculation, empty comparison, and null P&L in the new sensitivity ranking. For a tool used "every few weeks," the one day you run it during a Yahoo blip, you get nothing — **and no message explaining why.**

**Why this is worse than CODE_REVIEW M5:** M5 said a missing rate *understates put prices by a few percent*. That's true for the pricing step. But this delta-voiding behaviour is a far bigger blast radius — it removes the candidates entirely, upstream of pricing. M5's "surface r=0 in the report" fix (now in the v6 plan) does **not** address this, because the collapse happens before any pricing the report annotates.

**The fix is easy and financially sound:** delta is almost **insensitive to the risk-free rate** (r only nudges `d1` by `r·T`; over 30–90 days the delta of a 25-delta put barely moves between r=0% and r=5%). So `add_black_scholes_delta` should **fall back to `risk_free_rate = 0.0`** for the delta computation rather than voiding every delta:
```python
rate = 0.0 if risk_free_rate is None else float(risk_free_rate)
```
Keep the M5 annotation so the user knows the rate was unavailable. This preserves candidate selection and optionability on a rate-fetch failure, while the (small) pricing impact is the thing M5 already discloses.

**Recommend:** fix in a small follow-up (it touches `options_chain.py` + a test simulating `risk_free_rate=None` producing non-empty candidates). Not Codex's current batch, but high priority — flag it for right after Checkpoint B. Add a test: *"candidate grid is non-empty when risk_free_rate is None."*

---

## D-2 (Low) — ATM straddle can silently use a non-ATM strike on sparse chains
**File:** `options_chain.py:165-171`. `compute_straddle_implied_move` picks the common (put+call) strike nearest the underlying. On a thin chain whose nearest common strike is far from spot, the "ATM straddle" is actually off-ATM, biasing `implied_move_{h}d` (which the header compares against modeled downside). Consider rejecting (return `None, False`) when the chosen strike is more than, say, one strike-increment or X% from spot, so the implied-move-vs-modeled verdict isn't built on a mislabelled straddle. Low frequency given the optionable universe is liquid US names, but worth a guard.

## D-3 (Low) — IV upper gate may exclude legitimate cheap tail puts
**File:** `options_chain.py:233-237` / `options.py` thresholds. `option_quote_is_tradable` rejects `implied_volatility > max_implied_volatility` (default 3.0 = 300%). Deep-OTM puts on a volatile miner can legitimately print IV > 300%; those are exactly the cheap lottery-ticket puts a speculator might want. The 300% cap is generous, so this is minor, but worth knowing it's a deliberate exclusion, not a bug. Confirm 3.0 is the intended ceiling for the speculation use-case.

## D-4 (Low, informational) — `nearest_expiration` tiebreak prefers the shorter-dated expiry
**File:** `options_chain.py:128-140`. On an exact distance tie (target 60d, listings at 53d and 67d), it picks 53d (sorts by `days_to_expiry` ascending after distance). That's a reasonable default (less time premium), just undocumented. One comment line would make the intent explicit.

---

## What I checked and found correct (no action)
- **Normalization** (`normalize_options_chain`): column-rename map, required-column gate, `mid` fallback via `midpoint` (requires bid>0 & ask>0), `days_to_expiry > 0` filter, expiration/option_type/strike validity filtering — all sound and defensive.
- **Liquidity gates** (`quote_passes_liquidity_gates`): `bid/ask/mid > 0`, `(ask−bid)/mid ≤ max_spread_pct`, OI/volume floors — standard and correct. Spread-relative-to-mid is the right metric.
- **Straddle implied move** math: `(put_mid + call_mid)/spot` at the ATM common strike with both legs gated — correct construction (to-expiry move, comparable to the modeled-downside horizon).
- **Candidate selection** (`build_candidate_put_grid`): normalize → nearest expiry → puts-only → tradability filter → nearest-target-delta pick → `premium_pct_spot` — logically clean; the `days_to_expiry` 0-fallback is harmless given the upstream `>0` filter.
- **`strike_for_target_delta`**: closest-delta selection with strike tiebreak — correct.
- **Cross-sectional IV percentile** (`rank_options_iv_cross_section`): `rank(pct=True)*100` over `atm_iv_60d`, NaN-safe — correct.

---

## Priority
**D-1 is the one that matters** — it's a real, silent, universe-wide failure mode triggered by an external dependency (the `^IRX` quote) that the code already expects to fail sometimes. It's a ~3-line fix plus a test, and it should be done soon (right after Checkpoint B), independent of the report rewrite. D-2/D-3/D-4 are low-priority hardening/confirmations.

I can audit `expected_downside.py` and `implied_move.py` next (the two remaining report-feeding modules I haven't read end-to-end) if you want the data path covered completely before Checkpoint B.
```
