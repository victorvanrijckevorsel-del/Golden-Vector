# Plan — Total horizon consistency (one selected horizon → every number on the page is that horizon)

**Status:** DRAFT for review (Claude + Codex). Do not build until reviewed.
**Owner:** Claude. **Decision locked by Victor:** *"no discrepancy throughout the tool — no parameter is computed at 6 months while another on the same page is computed on another horizon."* Be as consistent as possible, everywhere. Centralise so nothing can drift.

---

## 1. The problem (confirmed by a code inventory, not a guess)

Today the structural-window switcher only *partially* drives the page. On the **ticker detail page**, when you pick a window:

| Follows the switcher (per-window) | Does NOT follow — fixed to a single anchor/aggregate |
|---|---|
| Structural Delta, Gamma, Asymmetry, R², Weeks | **Gold Sensitivity Score** (`tool_a_score`) |
| Up/Down Beta panel, Weekly Return Scatter | **Profile** (`profile_label`) |
| Volatility Diagnostics, Beta-vs-universe strip | **Confidence** (`confidence_label`) |
| Rebased overlay chart | **Rank** (`tool_a_rank`) |
| | **Explanation cards** (hybrid: active-window delta vs `*_core` aggregates) |

So at 3Y you see 3Y deltas under a Score/Confidence/Rank computed on the 1Y anchor. That is exactly the discrepancy Victor flagged. It exists **today on the 3 scoring windows** — 2Y/5Y just make it more visible.

Other surfaces with the same class of mismatch:
- **Overview / Gold Reactors list:** beta family follows the selector, but Confidence / Profile / **Rank** are fixed-anchor.
- **Portfolio page:** shows `down_beta_core` (fixed anchor), no selector → won't match a non-anchor detail page.
- **Candidate Finder:** no window selector; any gold-beta cri/basis is a hidden fixed window.

Two things are **legitimately cross-horizon and must NOT be forced onto the switcher** (they are *about* comparing horizons, so showing them is not a discrepancy — but they must be **clearly labelled** as multi-horizon):
- **Delta stability** (how steady the beta is *across* windows — inherently multi-window).
- **Exploratory Horizon Ladder** (short tactical 1d…1y single-period returns — a *different* horizon axis, not the 6M/1Y/2Y/3Y/5Y structural windows).

## 2. Root cause: window logic is scattered (the duplication to kill)

The inventory found the same concept defined in 12+ places: `serve/windows.py` (5-set + labels + aliases + suffix fn), `serve/workspace_state._WINDOW_WEEKS` (scoring-only — source of the volatility-mislabel bug), `model/structural._window_offset`, `model/benchmark_comparison._WINDOW_COLUMN_SUFFIX` + `_WINDOW_LABEL`, `model/tool_c` window cols, `serve/format_helpers.TOOL_A_NUMERIC_FIELDS` (scoring-only), `portfolio/benchmark_betas` display cols, and **config validators that hardcode `must be exactly 6M,12M,3Y`** in `contracts/config_models.py`. Good news already in place: `ConfidenceThresholds.minimum_observations_*` is **already configured for all 5 windows** (6M=20, 12M=40, 2Y=80, 3Y=120, 5Y=200).

## 3. Target architecture

### 3a. ONE window registry (foundation — build first)
A single source of truth, `golden_vector/common/windows.py` (or extend `serve/windows.py` and re-export), exposing per window id: `weeks`, calendar `offset`, `label` (12M→"1Y"), query `aliases`, column `suffix`, `min_observations`, and a `scored: bool` flag. Everything else imports from it. Delete the scattered tuples/dicts and the `_window_offset` ad-hoc parser; widen the config validators to accept the registry's set instead of hardcoding `6M,12M,3Y`. This kills the drift and is the prerequisite for everything below.

### 3b. Scoring/rank/confidence/profile become per-window (the real change)
`compute_tool_a_score` is a clean weighted sum of one window's `{delta, gamma, asymmetry, confidence}`; `rank` is a cross-sectional dense-rank of that score per `as_of_date`. So we compute and **persist a full metric set per window** for all five windows: `tool_a_score_{w}`, `tool_a_rank_{w}`, `confidence_score_{w}`, `confidence_label_{w}`, `profile_label_{w}`, plus the already-present delta/gamma/asymmetry/beta/R²/weeks/status. The pipeline already computes the per-window beta math for all 5; we extend the *scoring* step (currently filtered back to scoring windows) to run per window through the registry, gated by the per-window min-observations that already exist. **Rank becomes explicitly per-horizon:** "at a 5Y lookback, this miner ranks #N among all miners' 5Y scores."

### 3c. Cross-horizon metrics: keep, but label
`delta_stability` and the Exploratory Ladder stay as-is (they are multi-horizon by definition) but get an explicit "across all windows" / "tactical horizons, not the structural window above" label so they read as deliberate, not as a leak. Confirm during build whether `confidence`/score depend on `delta_stability` (cross-window); if so, define a per-window stability input or drop stability from the per-window confidence so each window's score is self-contained.

### 3d. Serve = read the active window's persisted columns
Every surface resolves *all* of its horizon-bearing numbers through the registry for the **one** active window: detail page (Score/Profile/Confidence/Rank now follow the switcher; explanation cards use active-window values only; the "Official Structural Windows" table either lists all five or is relabelled "all windows for reference"), overview (Rank/Confidence/Profile become per-window), portfolio + candidate finder (add a window control OR show a single clearly-labelled basis — see open decisions). No serve-side recompute — serve reads persisted per-window columns (compute-once → persist → serve reads).

## 4. Build sequence (spec rule: foundation → features → scoring → UI)
1. **Registry** (`common/windows.py`) + redirect all imports + widen config validators. Pure refactor, no behaviour change; full gate stays green.
2. **Per-window scoring** in `model/pipeline` + `model/scoring` (persist `*_score_{w}`, `*_rank_{w}`, `confidence_*_{w}`, `profile_label_{w}` for all 5). Reconstruction-parity tests updated.
3. **Serve reads per-window** for Score/Profile/Confidence/Rank on detail + overview; explanation cards active-window-only; volatility/overlay window-weeks via registry (fixes the 2Y/5Y mislabel).
4. **Surface rollout**: detail switcher → 5 windows; portfolio + candidate-finder decision applied.
5. **Guardrail test** (below) + labels for the cross-horizon metrics.

## 5. Tests / how we prove "no discrepancy"
- **Anti-mixing guardrail (new, the headline test):** render each stock-facing page at a non-anchor window and assert *every* horizon-bearing number on it resolves to that window — no `_core`/anchor value leaks when a window is selected. Clone the serve-arithmetic static-scan pattern for "no fixed-window column read in a switcher context."
- Registry unit tests (weeks/offset/label/suffix/min-obs for all 5; unknown id fails loud).
- Per-window scoring determinism + reconstruction-parity for all 5 windows (ties + NA included).
- Per-window rank: a deliberately-constructed universe where the 5Y ranking differs from the 1Y ranking, asserted.
- Full gate + live-verify on real data at each window.
- Adversarial review loop (`/review-loop`) until dry, as with the overlay.

## 6. Risks / methodology (predictive-models discipline)
- Per-window rank is a **methodology change**, not just display. It is statistically sound here — longer windows have *more* data (5Y=260 wk vs 6M=26), and min-observations gates already exist per window — but it must go through the **centralised config** (spec hard rule: no ad-hoc horizons) and be validated, not bolted on.
- Confirm no cross-window dependency sneaks into a per-window score (the `delta_stability` question in 3c).
- Bigger persisted schema (≈5× the per-window columns) → bump schema/method version; keep publish all-or-nothing.

## 7. Decisions (LOCKED by Victor 2026-06-20)
1. **Scope:** detail page + overview become fully per-horizon now. **Portfolio & Candidate Finder:** keep one clearly-labelled canonical basis ("gold beta @ 1Y") now; add real window selectors as a fast-follow — do NOT balloon this change with their UX.
2. **"Official Structural Windows" table:** keep all windows side-by-side, **relabelled** as an explicit cross-window reference table (deliberately multi-horizon, not a leak).
3. **The Score is per-horizon:** Score / Rank / Confidence / Profile all recompute on the selected window. A miner's "rating" becomes horizon-specific (e.g. #5 at 1Y, #12 at 5Y) — accepted and intended.

### Still to confirm during build (not blocking the plan)
- **Confidence vs stability:** if `confidence` currently depends on cross-window `delta_stability`, make each window's confidence self-contained so a per-window score has no cross-window leak. Verify in Phase 2.
