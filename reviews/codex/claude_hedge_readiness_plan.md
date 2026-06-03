# Plan: Hedge Readiness (Milestone 1 of the downside-product line)

**Author:** Claude Code
**Branch:** `dev-vic`
**Date:** 2026-05-29 (v2 after Codex review)
**Reviewer:** Codex — graded `NEEDS CHANGES` on v1; v2 addresses every finding
**Related:**
- [reviews/codex/codex_review_claude_hedge_readiness_plan.md](codex_review_claude_hedge_readiness_plan.md) — v1 review (this is what v2 responds to)
- [reviews/codex/codex_options_ideas_and_critique.md](codex_options_ideas_and_critique.md) — original brainstorming critique that reframed this milestone
- [reviews/codex/codex_tool_c_d_ideas_and_critique.md](codex_tool_c_d_ideas_and_critique.md) — earlier critique that introduced architectural ideas (margin under stress, risk tags, etc.)
- [[inflight-planning-tool-c-d]] memory

## v2 changelog (against Codex review)

| Codex finding | Where addressed in v2 |
|---|---|
| R1 — 25-delta interpolation rules inconsistent | §2f and §4 now specify: surface the LISTED strike whose computed delta is closest to −0.25, plus a `delta_gap` field. No interpolation reaches the user-facing grid. |
| R2 — Missing Yahoo IV fallback undecided | §2c, §2d, §3 (features module) now state: when Yahoo IV is null, delta and 25-delta IV are null for that contract. No Newton-Raphson solver in M1. |
| R3 — Implied-move on thin chains | §2d and §3 add liquidity gates: positive bid/ask, max spread %, min OI/volume, same-expiration put+call required. Thresholds in `config/hedge_readiness.yaml`. |
| R4 — `update-data` runtime escape hatch | §2a and §6 step 7 add `--options / --no-options` flag to `update-data`. Default keeps options on. Phase summary records run/skip. |
| R5 — Proxy similarity honesty | §2h and §3 (proxy_hedge module) rename to "down-beta similarity," add explicit basis-risk label, surface Tool A confidence + Tool B verdict as context (Tool B does NOT disqualify a proxy). |
| **R6 — GDX/GDXJ placement (BLOCKING)** | NEW `config/benchmarks.yaml` instead of universe.yaml (which has strict schema validation per `golden_vector/contracts/config_models.py:14`). Benchmarks fetched via dedicated hedge/options path, NOT through the foundation pipeline. Stay out of Tool A/B eligibility. |
| R7 — Report output | §5 and §7 now write report to `data/output/hedge_readiness/<as_of_date>_<run_id>.md` + `latest.md` alias. Print path + compact summary to stdout. Add `output_hedge_readiness_dir` to `ProjectPaths`. |
| **AF1 — Replay safety (BLOCKING)** | Storage layout reshaped: options snapshots now live at `data/runs/<run_id>/snapshots/options/<TICKER>.parquet` (run-local, immutable, mirrors foundation pattern). `data/intermediate/status/latest_options_manifest.json` points at the most-recent run. Replay manifest extended (small targeted addition) to capture the options manifest path, same way it captures the foundation manifest. No same-day overwrite anywhere. The `data/raw/options/` cumulative archive is removed from the plan. |
| AF2 — Raw schema includes derived delta | §2c removes `delta` from the raw schema. Delta lives only in the features layer. Raw = Yahoo fields + snapshot identity columns only. |
| AF3 — Report reads `latest.parquet` that never gets written | Resolved by AF1 fix: report reads via `latest_options_manifest.json` pointer, not via a `latest.parquet`. |
| AF4 — Holdings auto-creation inconsistency | §2e and §3 (holdings module) now state: missing `holdings.yaml` returns empty list silently. No implicit creation. Example file lives at `tests/fixtures/holdings/holdings_example.yaml`. |

---

## 0. The simplest thing that could work

Before any clever design:

> **Add a Yahoo-options fetcher modeled on the existing `fetch_equities.py` pattern, store raw chains per ticker per date as parquet, compute a small set of derived features and one hedge-candidate grid (30/60/90-day at ~25-delta puts) per optionable ticker, read an existing `holdings.yaml` to weight outputs by dollar exposure, map non-optionable tickers to a proxy via Tool A's down-beta similarity, and print a markdown report from a new `python main.py hedge-readiness` command. No workspace UI. No new dependencies beyond `yfinance` (already installed). No scipy — Black-Scholes deltas use `math.erf` for the normal CDF (verified at planning time, no new install).**

Everything below justifies, scopes, and grounds that baseline.

---

## 1. Current state (verified 2026-05-29)

### Existing infrastructure we'll reuse
- `golden_vector/ingestion/fetch_equities.py:15` `fetch_equity_histories(...)` — established Yahoo fetcher pattern. New `fetch_options.py` mirrors this.
- `golden_vector/ingestion/yahoo_client.py` — shared Yahoo HTTP client. Reuse it.
- `golden_vector/ingestion/persist.py` — parquet write helpers (`_write_parquet`, etc.). Reuse for raw chain persistence.
- `golden_vector/app/run_context.py:80` — `RunContext.start()` now auto-writes replay manifests. Any new command we add via `RunContext.start` automatically gets provenance.
- `golden_vector/cli.py` — argparse-subparser pattern (`subparsers.add_parser`). Add `hedge-readiness` as a new subparser.
- `golden_vector/app/paths.py` — `ProjectPaths` is the central path map. Add `options_raw_dir`, `options_features_dir`, `holdings_path` fields.

### Data we'll consume

| Source | What we read | Verified field names |
|---|---|---|
| `data/output/tool_a/tool_a_latest.parquet` | Down-beta for all 64 tickers, used for expected-downside math + proxy similarity | `down_beta_core`, `down_beta_12m`, `up_beta_core`, `confidence_score`, `r_squared_12m` |
| `data/output/tool_b/tool_b_latest.parquet` | Per-ticker share price (used for moneyness + premium-vs-spot) | `share_price_usd`, `market_cap_musd` |
| `data/runs/<run_id>/snapshots/raw_gold.parquet` | Gold history for IV-vs-RV ratio context (already retained via existing snapshots) | — |
| Yahoo `^IRX` | 13-week T-bill yield → risk-free rate for Black-Scholes | — |
| Yahoo `yfinance.Ticker(sym).option_chain(exp)` | Full options chain per ticker per expiration — `puts` and `calls` DataFrames | `strike`, `bid`, `ask`, `lastPrice`, `volume`, `openInterest`, `impliedVolatility` |

### Probed reality (from `claude_options_brainstorming_brief.md` reality check)
- **24 of 64 tickers have any options on Yahoo** (37.5% coverage)
- **All foreign listings** (`.AX`, `.TO`, `.V`, `.L`) return empty chains
- **Tier 1 (OI > 5k)**: ~19 names including NEM, GOLD, AEM, AGI, KGC, PRU, CDE, SSRM
- **Tier 2 (thin)**: ~5 names — FNV, TXG, CMCL, GAU, DRD
- **Tier 3 (no options)**: 40 names — every `.AX`/`.TO`/`.V`/`.L` listing plus NGD

Per the locked product decision, **we still fetch all 64.** Non-optionable tickers get `null` features and a flag; the proxy-hedge mapping covers them via Tool A similarity.

### What's NOT installed but we don't need
- `scipy` — verified absent. Black-Scholes delta uses `math.erf`:
  ```python
  def _normal_cdf(x: float) -> float:
      return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
  ```
  No new dependency.

---

## 2. Architecture

### 2a. Decisions locked across earlier conversations and Codex critiques

| Decision | Choice | Source |
|---|---|---|
| Storage layout (v2 — Codex AF1) | **Run-local snapshots:** `data/runs/<run_id>/snapshots/options/<TICKER>.parquet`. Pointer: `data/intermediate/status/latest_options_manifest.json` records which run owns the most-recent snapshots. Same pattern as foundation. **No `data/raw/options/` cumulative archive, no same-day overwrite anywhere.** Features (long-format, accumulating) still live at `data/intermediate/options_features/<TICKER>.parquet`. | v2 — Codex AF1 (replay safety) |
| Fetch scope | Everything Yahoo returns (all strikes, all expirations, both puts and calls) | Earlier user decision |
| Cadence + opt-out (v2 — Codex R4) | Daily, integrated into `update-data` by default. NEW `--no-options` flag skips the phase. Phase summary recorded in run metadata regardless. | v2 — Codex R4 |
| Risk-free rate | Daily `^IRX` fetch alongside existing equity fetches | Earlier user decision |
| IV source | Trust Yahoo's `impliedVolatility`, flag null | Earlier user decision |
| Deltas | Compute Black-Scholes using `math.erf` (no scipy) | Plan §1 verified |
| Failure mode | Best-effort per-ticker; failures recorded in run.log; run continues | Earlier user decision |
| Tests | Saved fixture chain at `tests/fixtures/options/`; no live Yahoo in suite | Earlier user decision |
| Output | CLI markdown report via `python main.py hedge-readiness`, no workspace UI | Codex critique adoption |
| Proxy hedges | Each non-optionable ticker maps to the most behaviorally-similar OPTIONABLE ticker (by Tool A down-beta) and to GDX/GDXJ with basis-risk flags | Codex critique adoption |
| Holdings | Simple YAML at `data/manual/holdings/holdings.yaml` — ticker + shares (or dollar exposure) | User decision after Codex critique |
| Horizons | 30 / 60 / 90 days side-by-side in the candidate-puts grid | User decision after Codex critique |
| 52-week IV percentile | **Cut from M1.** Needs history we don't have. Replaced with cross-sectional IV percentile within the 24 optionable gold names (works day-1). | Codex critique adoption |
| Days-to-earnings | **Cut from M1.** New Yahoo dependency not worth it for gold miners. | Codex critique adoption |
| Aggregate liquidity score | **Cut from M1.** Replaced with contract-level liquidity at the candidate strike. | Codex critique adoption |

### 2b. Module layout (target after this milestone)

```
golden_vector/
  ingestion/
    fetch_options.py             # NEW — Yahoo options chain fetcher per ticker per date
    fetch_risk_free_rate.py      # NEW — ^IRX daily fetcher
    fetch_benchmarks.py          # NEW (v2 — Codex R6) — GDX/GDXJ history fetcher; dedicated path, NOT in foundation
    persist_options.py           # NEW — writes run-local options snapshots + updates latest_options_manifest.json
  features/
    options.py                   # NEW — derived feature computation. Delta lives here (v2 — Codex AF2), NOT in raw schema.
    black_scholes.py             # NEW — pure math: normal CDF (math.erf), delta, nearest-listed-strike-by-delta selection (NOT interpolation, v2 — Codex R1)
  hedge/
    __init__.py                  # NEW — new subpackage
    holdings.py                  # NEW — load holdings.yaml; missing file = empty list, NO auto-creation (v2 — Codex AF4)
    candidate_puts.py            # NEW — surface LISTED strike closest to −0.25 delta per horizon, with delta_gap (v2 — Codex R1)
    implied_move.py              # NEW — ATM straddle implied move WITH liquidity gates (v2 — Codex R3)
    proxy_hedge.py               # NEW — "down-beta similarity" mapping with explicit basis-risk labels (v2 — Codex R5)
    expected_downside.py         # NEW — Tool A down-beta × gold scenarios → premium-vs-downside cards
    report.py                    # NEW — assemble report; writes to file + prints summary (v2 — Codex R7)
  app/
    paths.py                     # EDIT — add options_features_dir, holdings_path, latest_options_manifest_path, output_hedge_readiness_dir, benchmarks_dir
    replay_manifest.py           # EDIT (v2 — Codex AF1) — small targeted addition to capture the options manifest path
  contracts/
    config_models.py             # EDIT (v2 — Codex R6) — add BenchmarksConfig model so config/benchmarks.yaml validates cleanly
  cli.py                         # EDIT — add `hedge-readiness` subparser + handler; add `--no-options` flag to `update-data`
config/
  benchmarks.yaml                # NEW (v2 — Codex R6) — GDX/GDXJ (and any future benchmarks). NOT universe.yaml.
  hedge_readiness.yaml           # NEW — tunable thresholds: hedge-ratio bands, target_delta, target_horizons, implied-move liquidity gates, optionability_oi_threshold
data/intermediate/status/
  latest_options_manifest.json   # NEW — pointer to current run's options snapshots (mirrors latest_foundation_manifest.json)
data/runs/<run_id>/snapshots/options/
  <TICKER>.parquet               # NEW — per-run immutable options snapshots
data/output/hedge_readiness/
  <YYYYMMDD>_<run_id>.md         # NEW (v2 — Codex R7) — canonical report
  latest.md                      # NEW (v2 — Codex R7) — alias pointer
data/manual/holdings/
  holdings.yaml                  # User-maintained. Plan does NOT auto-create. (v2 — Codex AF4)
tests/
  fixtures/options/
    <fixture>.parquet            # NEW — saved Yahoo response for one ticker on one date
  fixtures/holdings/
    holdings_example.yaml        # NEW (v2 — Codex AF4) — example file referenced by docs and used by tests
  test_fetch_options.py          # NEW
  test_fetch_benchmarks.py       # NEW
  test_options_features.py       # NEW
  test_black_scholes.py          # NEW
  test_holdings.py               # NEW
  test_candidate_puts.py         # NEW
  test_implied_move.py           # NEW
  test_proxy_hedge.py            # NEW
  test_expected_downside.py      # NEW
  test_hedge_report.py           # NEW
  test_cli_hedge_readiness.py    # NEW
  test_cli_update_data_no_options_flag.py  # NEW (v2 — Codex R4)
  test_replay_manifest_captures_options.py # NEW (v2 — Codex AF1)
```

### 2c. Schema — raw options chain (one parquet per ticker per run; lives at `data/runs/<run_id>/snapshots/options/<TICKER>.parquet`)

**v2 — Codex AF2:** delta is removed. Raw = Yahoo fields + snapshot identity columns only. Derived fields (including delta) live in the features layer.

| Column | Type | Source / computation |
|---|---|---|
| `ticker` | str | Loop variable |
| `as_of_date` | date | Snapshot date |
| `run_id` | str | Owning run id (for cross-reference) |
| `expiration` | date | From `Ticker.options` |
| `option_type` | str | `"P"` or `"C"` |
| `strike` | float | Yahoo |
| `bid` | float? | Yahoo |
| `ask` | float? | Yahoo |
| `mid` | float? | `(bid + ask) / 2` when both present and positive, else null |
| `last_price` | float? | Yahoo |
| `volume` | int? | Yahoo |
| `open_interest` | int? | Yahoo |
| `implied_volatility` | float? | Yahoo (null when Yahoo couldn't compute). **Per Codex R2: no Newton-Raphson fallback in M1; null means null.** |
| `underlying_price` | float | Yahoo (price at fetch time, same for all rows in this file) |
| `moneyness` | float | `strike / underlying_price` |
| `days_to_expiry` | int | `(expiration - as_of_date).days` |

### 2d. Schema — derived features (long-format, one row per ticker per date per feature-set)

The features file accumulates over time so we can build IV percentile history later. One file per ticker.

**Notes per Codex review:**
- **R1:** `put_iv_25d_*` and `call_iv_25d_*` come from the LISTED strike whose computed delta is closest to ±0.25. New `put_25d_delta_gap_*` columns record |actual_delta − target_delta| so the user sees how well-matched the listed strike was.
- **R2:** when underlying IV is null, all delta-derived fields for that contract are null. No solver, no estimate.
- **R3:** `implied_move_*` is null when liquidity gates fail. Gate booleans surfaced as `implied_move_*_gates_ok` for transparency.

| Column | Notes |
|---|---|
| `ticker`, `as_of_date`, `run_id` | Primary key plus run cross-reference |
| `options_available` | bool — was the chain non-empty? |
| `n_expirations`, `n_contracts` | Sanity counts |
| `total_open_interest`, `total_volume` | Aggregate; kept for context but NOT used as a single liquidity score (per Codex critique) |
| `atm_iv_30d`, `atm_iv_60d`, `atm_iv_90d` | ATM IV at each horizon. Nearest-expiration selection; no interpolation across expirations. |
| `put_iv_25d_30d`, `put_iv_25d_60d`, `put_iv_25d_90d` | IV at the LISTED strike whose computed delta is closest to −0.25 within each horizon's nearest expiration |
| `put_25d_delta_gap_30d`, `put_25d_delta_gap_60d`, `put_25d_delta_gap_90d` | NEW (v2 — Codex R1) — `\|computed_delta − (−0.25)\|`. Tells the user how close the listed strike is to the target. |
| `call_iv_25d_30d`, `call_iv_25d_60d`, `call_iv_25d_90d` | Same shape for calls |
| `iv_skew_30d`, `iv_skew_60d`, `iv_skew_90d` | `put_iv_25d − call_iv_25d` at each horizon |
| `term_slope_30_90` | `atm_iv_90d − atm_iv_30d` |
| `implied_move_30d`, `implied_move_60d`, `implied_move_90d` | NEW gates per Codex R3: requires `bid > 0`, `ask > 0`, `spread_pct < threshold`, `min(put_oi, call_oi) > min_oi`, both put+call present at the same expiration. Null when gates fail. |
| `implied_move_30d_gates_ok`, `_60d_gates_ok`, `_90d_gates_ok` | NEW boolean transparency columns |
| `realized_vol_30d`, `realized_vol_60d`, `realized_vol_90d` | Trailing realized vol from existing price snapshot |
| `iv_rv_ratio_30d`, `iv_rv_ratio_60d`, `iv_rv_ratio_90d` | `atm_iv / realized_vol` at each horizon |
| `iv_percentile_cross_sectional` | Rank of this ticker's `atm_iv_60d` among the optionable set on the same date (0–100) |
| `put_call_oi_ratio_total`, `put_call_oi_ratio_otm` | Aggregate and OTM-only ratios |
| `optionability_tier` | `"directly_hedgeable"` (OI > threshold AND has all three horizons) / `"thin"` (some options but below threshold) / `"none"`. Threshold in `config/hedge_readiness.yaml`. |

### 2e. Holdings schema (`data/manual/holdings/holdings.yaml`)

```yaml
version: 1
holdings:
  - ticker: NEM
    shares: 500            # OR: dollar_exposure: 50000
  - ticker: AEM
    shares: 200
  - ticker: GFI
    shares: 1500
```

Minimal v1. We'll add `target_hedge_pct`, `max_premium`, notes in a future revision only if needed.

**v2 — Codex AF4:**
- If the file does NOT exist, the loader returns an empty list. No error, no auto-creation.
- An example file lives at `tests/fixtures/holdings/holdings_example.yaml` and is referenced from docs.
- If holdings is empty, the report still runs and shows the cross-sectional ranking + proxy map (no per-position cards).

### 2f. Candidate puts grid (per optionable ticker, written into the report)

For each optionable ticker, the report shows three rows:

| Horizon | Expiration | Strike | Moneyness | Δ | Δ-gap | Bid | Ask | Mid | Spread% | OI | Volume | Premium % of spot | Breakeven |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 30d | 2026-06-26 | 145 | 0.967 | -0.27 | 0.02 | 2.10 | 2.30 | 2.20 | 9% | 1,240 | 88 | 1.47% | 142.80 |
| 60d | 2026-07-31 | 142 | 0.946 | -0.25 | 0.00 | 4.10 | 4.40 | 4.25 | 7% | 940 | 32 | 2.83% | 137.75 |
| 90d | 2026-08-29 | 140 | 0.933 | -0.25 | 0.00 | 6.00 | 6.40 | 6.20 | 7% | 720 | 18 | 4.13% | 133.80 |

**Strike selection (v2 — Codex R1):** Among the **listed** strikes in each horizon's nearest expiration, surface the strike whose **computed delta** is closest to −0.25. Report the **listed strike** (no interpolation). The `Δ-gap` column shows how far that strike's delta is from −0.25. If `Δ-gap > 0.10` (configurable), the row is annotated `(target delta unavailable — nearest only)`. If no contracts in the expiration have computable delta (e.g., all IVs null per Codex R2), the row is shown as "no usable contract at this horizon" with the underlying counts.

### 2g. Premium vs. expected downside (the "is this cheap or expensive?" card)

For each owned + optionable ticker:

```
NEM ($150 spot, 500 shares = $75k exposure)
  Tool A down-beta (core): 1.42      Confidence: high (r² = 0.81)
  Expected stock drop if gold -10%:   -14.2% (≈ -$10,650)
  60-day 25Δ put premium:             2.83% of spot (≈ -$2,123 to hedge full notional)
  Hedge ratio (protection cost / expected drop): 0.20
  Tag: PROTECTION CHEAP — premium is well below modeled downside
```

Tags use simple bands on the hedge ratio:
- `< 0.30` → "PROTECTION CHEAP"
- `0.30 – 0.60` → "PROTECTION NORMAL"
- `0.60 – 1.00` → "PROTECTION EXPENSIVE"
- `≥ 1.00` → "PROTECTION OVERPRICED — premium exceeds modeled downside"

These bands are tunable in `config/hedge_readiness.yaml` (NEW config file).

### 2h. Proxy hedge mapping (per non-optionable ticker)

**v2 — Codex R5 + R6:** renamed from "behaviorally similar" to "down-beta similarity" to be honest about the method. Per-row basis-risk label. Tool A confidence + Tool B verdict shown as context but do NOT disqualify a proxy (a proxy is about traded behavior, not whether the proxy company is fundamentally attractive).

For each of the 40 non-optionable tickers, score down-beta similarity vs. each of the 24 optionable tickers + GDX + GDXJ:

```
down_beta_similarity = 1 - clamp(|down_beta_diff| / max_beta_diff, 0, 1)
where down_beta_diff = abs(target.down_beta_core - candidate.down_beta_core)
      max_beta_diff is configurable in config/hedge_readiness.yaml
```

A confidence multiplier scales the score down for weak `confidence_score` on either side.

**Basis-risk label** (assigned per pair):
- `low` — down-beta within 0.10 AND both tickers have `confidence_score >= 0.7`
- `medium` — down-beta within 0.30 AND at least one side has decent confidence
- `high` — anything else where similarity is non-trivial; flag explicitly

Surface the top 3 matches per non-optionable target with the label.

**GDX/GDXJ data path (v2 — Codex R6):** These benchmarks are NOT in `config/universe.yaml` (which has strict schema validation that would reject `is_benchmark: true`). They live in NEW `config/benchmarks.yaml`, are fetched via NEW `golden_vector/ingestion/fetch_benchmarks.py`, and persist to `data/runs/<run_id>/snapshots/benchmarks/<TICKER>.parquet`. They do NOT feed Tool A or Tool B; they are hedge-side-only inputs.

---

## 3. Code module summaries

### `golden_vector/ingestion/fetch_options.py` (~120 lines)

```python
def fetch_options_chain(
    *, ticker: str, as_of_date: date, yahoo_client: YahooClient
) -> OptionsChainResult:
    """Fetch all expirations + strikes + puts + calls for one ticker on one date.

    Returns a structured result distinguishing:
    - SUCCESS: chain present, DataFrame populated, underlying_price captured
    - EMPTY: ticker exists but no options listed (typical for foreign listings)
    - ERROR: Yahoo call failed with details
    """

def persist_options_snapshot(paths: ProjectPaths, ticker: str, chain: pd.DataFrame, as_of_date: date) -> Path:
    """Write to data/raw/options/<TICKER>/<YYYYMMDD>.parquet (overwrite on same-day re-run)."""
```

### `golden_vector/ingestion/fetch_risk_free_rate.py` (~40 lines)

```python
def fetch_risk_free_rate(as_of_date: date, yahoo_client: YahooClient) -> float:
    """Fetch ^IRX (13-week T-bill yield) and return as decimal (e.g. 0.0432)."""
```

### `golden_vector/features/black_scholes.py` (~80 lines, pure math, no Yahoo, no I/O)

```python
def normal_cdf(x: float) -> float:
    """Standard normal CDF via math.erf — no scipy needed."""

def black_scholes_delta(
    *, option_type: Literal["P", "C"],
    spot: float, strike: float, time_to_expiry_years: float,
    risk_free_rate: float, implied_volatility: float
) -> float | None:
    """Returns signed delta. Puts are negative; calls are positive.
    Returns None for degenerate inputs (zero time, missing IV, etc.).
    """

def strike_for_target_delta(
    *, option_type: Literal["P", "C"], target_delta: float,
    chain_slice: pd.DataFrame,  # one expiration's worth, with delta column populated
) -> dict | None:
    """Linearly interpolate within the chain to find the strike with delta closest
    to target_delta. Returns dict with strike, expiry, bid, ask, mid, oi, volume, iv, delta.
    Returns None if no contracts on either side of target_delta.
    """
```

### `golden_vector/features/options.py` (~200 lines)

```python
def compute_options_features(
    *, chain: pd.DataFrame,
    underlying_price: float,
    risk_free_rate: float,
    price_history: pd.DataFrame,  # for realized vol
    as_of_date: date,
) -> dict:
    """Compute the derived feature row defined in §2d.
    Returns the dict matching the long-format schema.
    Handles empty chain by returning a row with options_available=False and all numeric features null.
    """
```

### `golden_vector/hedge/holdings.py` (~50 lines)

```python
def load_holdings(paths: ProjectPaths) -> list[Holding]:
    """Read holdings.yaml. Returns empty list if file missing (do not error).
    Validates ticker is a string and shares (or dollar_exposure) is numeric and positive.
    """

@dataclass
class Holding:
    ticker: str
    shares: float | None
    dollar_exposure: float | None  # one of shares or dollar_exposure must be set
```

### `golden_vector/hedge/candidate_puts.py` (~80 lines)

```python
def build_candidate_put_grid(
    *, ticker: str, chain: pd.DataFrame, underlying_price: float,
    target_horizons_days: tuple[int, ...] = (30, 60, 90),
    target_delta: float = -0.25,
) -> list[CandidatePut]:
    """For each target horizon, find the nearest expiration and the strike closest to -25 delta.
    Returns up to 3 CandidatePut rows. Skips horizons with no available expirations.
    """
```

### `golden_vector/hedge/implied_move.py` (~30 lines)

```python
def compute_implied_move_from_straddle(
    *, chain: pd.DataFrame, underlying_price: float, expiration: date
) -> float | None:
    """Implied move = (ATM put mid + ATM call mid) / spot."""
```

### `golden_vector/hedge/expected_downside.py` (~80 lines)

```python
def compute_premium_vs_downside(
    *, ticker: str, down_beta: float, confidence_score: float,
    holding: Holding, candidate_put: CandidatePut,
    gold_scenarios: tuple[float, ...] = (0.05, 0.10, 0.20),
) -> PremiumVsDownsideCard:
    """For each gold-down scenario, estimate stock drop, compare to put premium.
    Returns a card with the cheap/normal/expensive tag.
    """
```

### `golden_vector/hedge/proxy_hedge.py` (~80 lines)

```python
def map_proxy_hedges(
    *, non_optionable_tickers: list[str],
    optionable_tickers: list[str],
    tool_a_frame: pd.DataFrame,
    benchmark_tickers: tuple[str, ...] = ("GDX", "GDXJ"),
    top_n: int = 3,
) -> dict[str, list[ProxyMatch]]:
    """For each non-optionable ticker, score similarity vs each optionable ticker and benchmark.
    Returns top-N matches per non-optionable target.
    """
```

### `golden_vector/hedge/report.py` (~200 lines)

```python
def render_hedge_readiness_report(
    *, paths: ProjectPaths, as_of_date: date,
) -> str:
    """Assemble the full markdown report. Reads:
    - data/manual/holdings/holdings.yaml
    - data/intermediate/options_features/<TICKER>.parquet (latest row per ticker)
    - data/raw/options/<TICKER>/latest.parquet
    - data/output/tool_a/tool_a_latest.parquet
    - data/output/tool_b/tool_b_latest.parquet
    Returns the report as a string (caller prints to stdout).
    """
```

### `golden_vector/cli.py` (edit, ~40 lines added)

```python
# Add subparser
hedge_parser = subparsers.add_parser("hedge-readiness", help="Print a hedge-readiness report for held positions.")

# Add dispatch in main()
if args.command == "hedge-readiness":
    return run_hedge_readiness(paths)

# New function
def run_hedge_readiness(paths: ProjectPaths) -> int:
    """Reads latest options features + Tool A + holdings, prints markdown report.
    Returns 0 if successful, 1 if a required input is missing (e.g., no Tool A run yet).
    """
```

### `update-data` integration (edit `golden_vector/cli.py`)

After the existing foundation phase, add a new options-ingestion phase:
```python
# After foundation_snapshot is loaded
options_summary = run_options_ingestion_phase(
    run_context=run_context, paths=paths,
    foundation_snapshot=foundation_snapshot,
)
```

`run_options_ingestion_phase` lives in a new module `golden_vector/ingestion/options_phase.py` and:
1. Loops over universe tickers, fetches chains, persists raw
2. Fetches `^IRX` once
3. Computes options features per ticker, appends to `data/intermediate/options_features/<TICKER>.parquet`
4. Returns a summary (n_success, n_empty, n_failed) written into run metadata

Failure modes (per Codex R-best-effort):
- Per-ticker chain fetch failures: logged to run.log, ticker skipped, run continues
- `^IRX` fetch failure: features computed without delta (degraded but not blocking)
- Persistence failure: hard-fails the run (this is real corruption risk)

---

## 4. Black-Scholes math — concrete

```python
import math

def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def black_scholes_delta(*, option_type, spot, strike, time_to_expiry_years, risk_free_rate, implied_volatility):
    if time_to_expiry_years <= 0 or implied_volatility is None or implied_volatility <= 0:
        return None
    if spot <= 0 or strike <= 0:
        return None
    t = time_to_expiry_years
    sigma = implied_volatility
    d1 = (math.log(spot / strike) + (risk_free_rate + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    if option_type == "C":
        return normal_cdf(d1)
    else:  # "P"
        return normal_cdf(d1) - 1.0
```

This is ~15 lines of standard math. No scipy. Returns `None` for degenerate inputs.

**v2 — Codex R1:** Drop interpolation entirely from the user-facing path. The function `strike_for_target_delta` selects the **single listed strike** whose computed delta is closest to the target. It returns a dict with the listed strike's actual values (strike, bid, ask, mid, oi, volume, iv, delta) and a `delta_gap` field showing `|computed_delta − target_delta|`. The candidate-puts grid renders this listed strike directly. No interpolated bid/ask/OI is ever produced or shown. Interpolated values are not tradable; surfacing them would mislead the user.

---

## 5. Report format (real-world preview)

```
# Hedge Readiness Report
As of: 2026-05-29
Holdings file: data/manual/holdings/holdings.yaml (3 positions, $182,000 total exposure)
Replay manifest: data/runs/<run_id>/replay_manifest.json
Cross-sectional IV ranking: 24 optionable gold tickers as of 2026-05-29

## Positions you hold

### NEM (Newmont) — 500 shares × $150.00 = $75,000 exposure
- **Risk profile:** down-beta 1.42 (high confidence, r²=0.81), Tool B verdict PASS, scenario downside @ gold -10%: **-14.2%** (≈ -$10,650)
- **Optionability:** directly hedgeable (OI 11,957, vol 1,931)
- **IV context:** IV/RV ratio 0.92 (cheap vs realized), cross-sectional IV percentile: 38th
- **Candidate puts:**
  | Horizon | Expiry      | Strike | Δ     | Bid  | Ask  | Mid  | Spr% | OI    | Vol | Prem % spot | Breakeven |
  |---------|-------------|--------|-------|------|------|------|------|-------|-----|-------------|-----------|
  | 30d     | 2026-06-26  | 145    | -0.27 | 2.10 | 2.30 | 2.20 | 9%   | 1,240 | 88  | 1.47%       | 142.80    |
  | 60d     | 2026-07-31  | 142    | -0.25 | 4.10 | 4.40 | 4.25 | 7%   |   940 | 32  | 2.83%       | 137.75    |
  | 90d     | 2026-08-29  | 140    | -0.25 | 6.00 | 6.40 | 6.20 | 7%   |   720 | 18  | 4.13%       | 133.80    |
- **Premium vs downside (60d):** hedge ratio 0.20 → **PROTECTION CHEAP** (premium is well below modeled downside)

### AEM — 200 shares × $180.00 = $36,000 exposure
[same shape]

### GFI — 1500 shares × $14.40 = $21,600 exposure
[same shape — note GFI has thin options, surface that]

## Non-optionable positions in your book
(none in this example — but if held, would list each with proxy mapping)

## Cross-sectional context — optionable gold names ranked by IV percentile (60d ATM)
| Rank | Ticker | ATM IV 60d | IV percentile | IV/RV ratio | Owned? |
|------|--------|------------|---------------|-------------|--------|
| 1    | DRD    | 78%        | 100th         | 1.42        |        |
| 2    | EQX    | 65%        | 92nd          | 1.18        |        |
| ...  |        |            |               |             |        |

## Proxy-hedge map (for the 40 non-optionable universe tickers, top match shown)
| Non-optionable | Closest optionable | down-β similarity | GDX similarity | GDXJ similarity | Note |
|----------------|--------------------|--------------------|----------------|------------------|------|
| KGC            | NEM                | 0.94               | 0.76           | 0.61             |      |
| ARIS.TO        | EQX                | 0.88               | 0.71           | 0.74             | basis-risk: medium |
| ...            |                    |                    |                |                  |      |

## Run summary
- Optionable tickers fetched: 24 / 24 success
- Empty chains (foreign): 40 (expected)
- Risk-free rate: 4.28% (^IRX as of 2026-05-29)
- Total open interest across universe: 412,883 contracts
- Total volume: 35,127 contracts
```

---

## 6. Order of operations

**v2 ordering — addresses Codex AF1 (replay-safe storage must exist before the ingestion fetcher writes anything) and Codex R6 (benchmarks config must exist before fetch_benchmarks).** Three new steps added; step ordering reflows.

| # | Step | Test gate |
|---|---|---|
| 1 | Add `config/benchmarks.yaml` + `BenchmarksConfig` model in `contracts/config_models.py`. Tests: schema validation, file load, rejection of unknown fields. NO ingestion yet. | Suite green; new schema tests pass |
| 2 | Add `golden_vector/ingestion/persist_options.py` (run-local snapshot writer + `latest_options_manifest.json` updater). Tests against tmp_path fixtures. Mirrors the foundation manifest pattern. NO fetcher yet. | Suite green |
| 3 | Extend `replay_manifest.py` to capture the options manifest path alongside the foundation manifest. Tests for: options manifest present, options manifest absent. | Suite green; new replay test passes |
| 4 | Add `fetch_options.py` + `fetch_risk_free_rate.py` + `fetch_benchmarks.py`. Tests against committed fixture chains. NO CLI wiring yet. | Suite green; fixture file committed |
| 5 | Add `black_scholes.py` (pure math, no I/O, no scipy). Comprehensive tests including parity vs known reference values, edge cases (zero time, missing IV, negative or zero prices). Includes `strike_for_target_delta` (LISTED strike + `delta_gap`, no interpolation per Codex R1). | Suite green; ~12 new tests |
| 6 | Add `features/options.py` (derived features per ticker per date, including delta computation and implied-move liquidity gating per Codex R3). Tests using the fixture chain. | Suite green |
| 7 | Add `hedge/holdings.py` (yaml load; missing file = empty list, no auto-create per Codex AF4). Tests for missing file, malformed file, valid file, mixed shares/dollar_exposure. | Suite green |
| 8 | Add `hedge/candidate_puts.py`, `hedge/implied_move.py`, `hedge/expected_downside.py`. One commit per file or grouped — Codex chooses, states in progress log. | Suite green |
| 9 | Add `hedge/proxy_hedge.py` (down-beta similarity with basis-risk labels per Codex R5). | Suite green |
| 10 | Add `config/hedge_readiness.yaml` with all tunable thresholds (optionability OI threshold, hedge-ratio bands, target_delta default, target_horizons, implied-move liquidity gates, delta_gap warning threshold, proxy max_beta_diff). Add `HedgeReadinessConfig` model. | Suite green |
| 11 | Add `hedge/report.py` + new `python main.py hedge-readiness` CLI subcommand. Report writes to `data/output/hedge_readiness/<YYYYMMDD>_<run_id>.md` + `latest.md` (per Codex R7); stdout prints path + compact summary. Tests render the report against fixture data and assert on key markdown markers. | Suite green; manual `python main.py hedge-readiness` on real data produces a file + summary line |
| 12 | Wire options ingestion phase into `update-data` with new `--no-options` / `--options` flag (default keeps options on per Codex R4). Best-effort per-ticker failure handling; phase summary written into run metadata. Same-day re-run creates a NEW run id (no overwrite). Also wire `fetch_benchmarks` into the same phase. | Suite green; manual smoke: run `update-data`, verify options snapshots appear under `data/runs/<run_id>/snapshots/options/`, verify `latest_options_manifest.json` points at the new run, verify report still works |
| 13 | Update `docs/` with a brief "Hedge Readiness" section explaining the workflow, the report format, the holdings file (referencing the example fixture), and the `--no-options` flag. | Suite green |

Each step = one commit. Progress log committed alongside per the workspace-split lesson.

---

## 7. Acceptance criteria

The milestone is done when **all** of the following hold:
- `python main.py update-data` writes a raw options chain parquet to `data/runs/<run_id>/snapshots/options/<TICKER>.parquet` for every optionable universe ticker, and an empty-chain marker (`options_available=False`) for non-optionable tickers, without crashing.
- `data/intermediate/status/latest_options_manifest.json` is updated to point at the most-recent run's options snapshot directory.
- The replay manifest for that run records `latest_options_manifest_sha256` and the options manifest path (v2 — Codex AF1).
- `data/intermediate/options_features/<TICKER>.parquet` gets a new row appended per ticker per `update-data` run.
- `python main.py update-data --no-options` skips the options phase cleanly and records that decision in run metadata (v2 — Codex R4).
- Same-day re-runs of `update-data` create distinct run ids and distinct options snapshots — NO overwrite of any options file (v2 — Codex AF1).
- `python main.py hedge-readiness` runs both without `holdings.yaml` (falls back to cross-sectional report only) and with a populated `holdings.yaml`.
- The report is written to `data/output/hedge_readiness/<YYYYMMDD>_<run_id>.md` and `latest.md` is updated to point at it. Stdout prints the path + compact summary (v2 — Codex R7).
- The report includes: per-position candidate-puts grids (with `Δ-gap` column), premium-vs-downside cards, cross-sectional IV ranking, and proxy-hedge mapping for non-optionable names (with explicit basis-risk labels).
- Every optionable ticker in the report has a candidate put at each of 30/60/90-day horizons OR an explicit "no usable contract at this horizon" message (per Codex R1+R2).
- Every non-optionable held ticker has at least one proxy recommendation with a basis-risk label.
- Implied move is shown only when liquidity gates pass; null fields explicitly marked (v2 — Codex R3).
- Full test suite passes with the new fixture-based tests; no live Yahoo calls in the suite.
- `config/benchmarks.yaml` validates cleanly; GDX/GDXJ are NOT in `config/universe.yaml` and NOT consumed by Tool A/B (v2 — Codex R6).

---

## 8. Out of scope (deliberately)

- **Tool C and Tool D** (downside-risk + fragility ranking pipelines) — these are Milestone 2 of the downside-product line.
- **Workspace UI integration** — no `/hedge-readiness` web page in M1. CLI markdown only.
- **52-week IV percentile** — needs accumulated history; deferred until we have ≥ 13 weeks of options snapshots.
- **Days-to-next-earnings** — cut from M1 per Codex critique; gold-price events dominate earnings dates for miners.
- **Options for foreign-listed names** — accept "not optionable" as a valid signal; no US ADR mapping.
- **Live options-trading integration** — read-only report only.
- **Live Greeks beyond delta** — no gamma, vega, theta in M1. Delta is the only one we need for 25-delta strike identification.
- **Recommended hedge contracts beyond shortlist** — we surface 3 candidates per ticker; we do NOT pick one for the user.
- **Holdings auto-import from a broker API** — manual YAML only in v1.
- **Position-history backtesting** — replay manifest captures inputs but a "what would the report have said last month?" command is M2+.

---

**v2 status:** All 7 original risks from v1 are now resolved per Codex's recommendations. The v2 remaining risks are smaller and listed below for Codex's re-review focus.

1. **Same-day re-run inflation.** Each `update-data` re-run now creates a new run id with full options snapshots (~24 small parquets). On a heavy debugging day this could mean 5-10 sets of options snapshots per ticker. Acceptable per the replay-safety priority, but Codex should flag if the disk growth feels untenable.
2. **`fetch_benchmarks` lives outside the foundation pipeline.** This is intentional (Codex R6), but it means GDX/GDXJ history doesn't get the same QA/normalization Tool A/B inputs get. For proxy-hedge similarity that's probably fine (we use raw prices to compute returns/beta). Confirm the contract: benchmarks are hedge-layer-only.
3. **`Δ-gap` warning threshold.** Plan sets it at 0.10 (configurable). If the threshold is too loose, the candidate-puts grid surfaces strikes the user shouldn't actually trade. If too tight, the grid is empty too often. Codex's view on the right default?
4. **Replay-manifest hash of `latest_options_manifest.json`.** When we extend the replay manifest (step 3), is hashing the pointer file enough, or should we also hash a manifest-of-snapshots inside each run's `options/` directory? The foundation manifest precedent suggests hashing the pointer is enough. Confirm.
5. **Empty-chain marker design.** Plan writes a small parquet with `options_available=False` per non-optionable ticker per run. Alternative: don't write a parquet at all; let absence mean "no chain." Marker is more explicit but consumes ~40 small files per run. Codex preference?

---

## 10. Implementation guidance for Codex

(Following the workspace-split / replay-manifest pattern.)

### Git workflow
- Branch `dev-vic`. Confirm with `git branch --show-current`.
- One commit per step in §6. Nine steps → nine commits.
- Commit message format: `hedge readiness step <N>: <one-line description>`
- Progress log committed alongside each step (two files per commit minimum).
- No amend, no rebase, no force-push, no skip-hooks, no `git push` — Emanuel pushes.
- One commit = one stated purpose. If you decide to do additional work mid-step (improvement, fix), commit the planned step first, then commit the extra work separately.

### Test gate
- `python -m pytest -q` between every step. All green, no new warnings, test count ≥ baseline.
- If a step breaks tests, STOP. Revert with `git reset --soft HEAD~1`, fix, re-commit. 15-minute fix cap.

### Self-cross-check rhythm at every step (MANDATORY — do not skip)

This is the same rhythm that worked on the workspace-split and replay-manifest milestones. Past steps where this was skipped or rushed are exactly where I caught real issues in review (step-7 Unicode normalization, step-2 duplicate `_write_metadata`). Do not let me catch the next one — catch it yourself first.

**Before committing step N — read your own diff:**
1. `git diff --staged` end-to-end. Read every line. Not skim.
2. For each chunk, ask:
   - Does this match what step N said to do?
   - Did I touch any file the step didn't mention? If yes, why?
   - Did I edit any comment, docstring, type hint, or whitespace that I didn't intend to edit?
   - Did any imports get added or removed beyond what the step required?
   - Is there any "small improvement" I slipped in that wasn't planned? (e.g., renaming a variable, normalizing a string, cleaning up adjacent code)
3. If you find anything that doesn't belong, **fix it in this commit before staging.** Do not commit and "fix later." Do not commit and "explain in the progress log."

**After committing step N — verify your own work:**
1. `python -m pytest -q` — must be green, test count must be ≥ baseline + any new tests this step added.
2. Re-read the relevant plan section (§2 / §3 / §6 of this plan) and **explicitly check** that step N's acceptance is met. Examples per step type:
   - Ingestion step: open the produced parquet, confirm the schema columns match §2c exactly.
   - Math step: run the test suite, plus a quick `python -c` invocation against a known reference value.
   - CLI step: actually run the command and read the output.
3. **If you find a bug or a deviation from the plan** — fix it before starting step N+1. Either:
   - Amend a follow-up commit with a clear "step N fix: <description>" message; OR
   - If the fix is trivial (~1-3 lines), squash into a single follow-up "step N fix" commit before moving on.
4. **Do NOT proceed to step N+1 with known bugs in step N.** This rule applies even if the bug seems "I'll fix it later in step N+2 anyway." Carrying bugs across steps is what makes debugging take 10x longer.

**Catch-criteria — if you see ANY of these, STOP and report at checkpoint (don't push through):**
- Test count dropped
- A test that was green now errors or skips
- A grep verification fails (a symbol you moved is still in two places, or a constant you renamed still exists with the old name)
- Your own diff has changes you can't explain in one sentence
- You spent more than 15 minutes trying to fix one issue

**Why this matters specifically for Hedge Readiness:**
- The plan involves real-money decision math (Black-Scholes deltas, premium-vs-downside). A sign error or a missing null check could mislead a user into a bad trade. The self-check rhythm is not bureaucracy — it's the only thing standing between "tests passed" and "the output is actually correct."
- The replay-safety storage layout (run-local snapshots + manifest pointer) is structurally important. A silent overwrite anywhere defeats the entire AF1 fix. Verify after every storage-touching step.

**Past failure modes to actively look for:**
- Unicode → ASCII normalization in moved or copied text (workspace-split step-7 incident)
- Duplicate function calls left in as defensive code without comments (replay-manifest step-2 incident)
- "Improvements" bundled into a fix commit that the commit message doesn't mention (replay-manifest step-7-fix incident)
- Imports added that look needed but are actually unused (replay-manifest step-9 finding)
- Stray blank lines accumulating across moves (workspace-split steps 3-7)

### Progress log
Create `reviews/codex/codex_hedge_readiness_progress.md` at session start with baseline. Append one line per step:
```
Step <N> (<step-name>): committed <sha>. Tests: <pass>/<total>. Fixture smoke: <yes/no/n-a>. Notes: <one line>.
```

### Checkpoints — STOP and report at each (v2 step numbers)
- **CHECKPOINT A** — after step 5 (storage layout + replay-manifest extension + ingestion + Black-Scholes math all in place, no hedge-product code yet). Report: tests added, all passing, fixture chain committed, replay-manifest options capture verified. Wait for "continue."
- **CHECKPOINT B** — after step 11 (full `hedge-readiness` CLI command working with file output). Report: paste a real markdown report produced by `python main.py hedge-readiness` against current data. Wait for "continue."
- **CHECKPOINT C** — after step 13 (final). Write the completion report (see §11). Wait for review.

### Out of scope — DO NOT do any of these
- Tool C or Tool D anything
- Workspace UI work (HTML, lenses, detail page, overview pages)
- Calling external paid APIs
- Backfilling historical options data
- Computing greeks beyond delta
- Anything outside the files named in §2b except `docs/` updates per step 9 and `config/hedge_readiness.yaml` per step 8

### If anything is ambiguous
Stop and ask. The plan is specific by design. If it doesn't cover your case, that's a signal to pause, not to invent.

### Start now
1. Confirm branch: `git branch --show-current` → `dev-vic`
2. Baseline: `python -m pytest -q` and record pass count
3. Create `reviews/codex/codex_hedge_readiness_progress.md` with baseline
4. Re-read this plan and confirm the design is consistent with what your critique recommended
5. Begin step 1
6. Stop at **CHECKPOINT A** and report

---

## 11. Completion report (write at CHECKPOINT C)

Write `reviews/codex/codex_hedge_readiness_completion_report.md` covering:

1. **Final file changes** — list every file added/modified with line counts
2. **Deviations from the plan** — every judgment call not specified, with `file:line` references. If none, say so
3. **Schema example** — paste a real raw chain parquet (head + tail) and a real options features row produced by a fixture run
4. **Report example** — paste a real markdown report produced by `python main.py hedge-readiness` against fixture or real data
5. **Test deltas** — baseline pass count, final pass count, new test files added, modified tests
6. **Edge cases verified** — table mapping each edge case (no holdings, no Tool A, no options, foreign ticker, missing IV, locked SQLite during update-data, etc.) to the test that covers it
7. **Risks resolved** — for each of the 7 risks in §9, what you decided + where it lives in code
8. **Open questions for the reviewer** — anything you want Claude to focus on

Keep it short and structured. Claude will use it as a guided tour of the diff.

---

## 12. Why this plan is shaped this way

| Principle | How it shows up |
|---|---|
| Simplest thing first | §0 states the no-frills version. Each addition justified. |
| Match rigor to risk | Real money decision tool → full plan + Codex review (correct rigor). |
| No premature abstraction | One subpackage (`hedge/`), one CLI command, one config file, no plugin system. Tool C/D explicitly deferred. |
| Don't redo work | Reuses existing Yahoo fetcher pattern, RunContext+replay manifest, ProjectPaths, Tool A/B published outputs. |
| Honest about limitations | §1 calls out 37.5% optionability coverage explicitly. §8 lists what M1 deliberately doesn't solve. |
| Verifiable | The CLI report is the proof of user value. Tests + fixture cover behavior. |
| User value first | The hedge-candidate grid, premium-vs-downside cards, and proxy-hedge mapping all answer concrete user questions, not just descriptive features. |
| Plain English | Section headers describe what's being decided, not just what's being done. |
