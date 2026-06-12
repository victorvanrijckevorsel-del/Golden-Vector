# Round-2 adversarial fleet — findings + fixes (2026-06-12)

Second fleet after the storage/compute review: 6 lenses (model math, option
math, lab statistics, web surface, test quality, concurrency). The three
MATH lenses died twice on session limits/connection resets and are running
a third time — their findings will be appended. Web/test/concurrency
returned in full; every fix below is committed and gated.

## Workspace outage (user-reported) — root cause + fix

The 503s on `/`, `/candidate-finder`, `/option-trading` were NOT a code or
data bug: the two long-running servers (ports 8780/8788) were started
before the schema-v3 milestones shipped — old in-memory code crashed on the
new manifest. A fresh app instance returned 200 with the designed
"unavailable until a market-hours refresh" notices on every page. Fix:
killed both stale servers, started one current server on 8788 (all pages
200), and scheduled a one-shot market-hours refresh (15:53 local) to mint
v3 option artifacts. Codex's handoff interpretation ("partial refresh
state, fail-closed working") was right about the data layer, but missed
that the 503-vs-notice difference was server staleness.

## Web surface lens — substantially CLEAN

14 attack classes verified OK end-to-end through a real WSGI harness:
static-file traversal (10 payloads incl. encoded/backslash/drive-letter),
stored XSS via notes (script/img payloads escaped at render), 404/search/
bucket/query echo escaping, open redirect via return_to (5 payloads),
scenario numeric parsing (9 edge cases), lot-id route edges, download
endpoints, portfolio 403 gating. Two findings, both fixed:
- **MEDIUM:** `?size_mode=budget&budget=inf` 500d the sizing calculator
  (`int(inf)` deep in sizing math) → non-finite now parses as None and
  falls into the existing "Invalid budget" note.
- **LOW:** malformed POST charset → generic 500 → decodes with
  errors=replace.

## Concurrency lens — 13 findings, the serious ones fixed

- **HIGH (fixed):** no PermissionError retry on atomic publishes — on
  Windows, `os.replace` fails the moment ANY reader holds the destination
  open, and the server reads latest aliases on every request. All three
  shared atomic writers (+ replay_manifest's three) now retry briefly on
  PermissionError only, then fail loud.
- **MEDIUM (fixed):** lock acquisition was read-check-write with a real
  race window (two workspace servers demonstrably run in practice) — both
  acquisition paths now serialize through an O_CREAT|O_EXCL sidecar with a
  re-check under it; crash leftovers older than 60s are broken.
- **MEDIUM (fixed):** PID reuse could leave the lock RUNNING forever
  (refresh button dead until a hand-delete) — 2h runtime ceiling recovers
  it with an explicit "stale after ceiling" message.
- **MEDIUM (fixed, proven by the agent):** a torn final ledger line MERGED
  with the next append — the registration was then silently quarantined and
  n_trials undercounted (weakens multiple-testing corrections). Appends now
  newline-guard; quarantine rewrites the ledger clean. Regression test
  proves both registrations survive a torn line.
- **MEDIUM (fixed):** manual vintage recorder racing the refresh-end
  recorder could lose rows (read-modify-rewrite) → manual runs defer to a
  live refresh owned by another process.
- **MEDIUM (fixed):** prune-runs hardened — refuses --apply during a live
  refresh; 24h age floor on run-dir candidates (a blocked publish leaves
  its run dir unreferenced and was deletable same-day).
- **LOW (fixed):** unbounded option-trading cache (one multi-MB generation
  leaked per refresh) → bounded LRU(4); stale-lock recovery write can no
  longer 500 a GET.
- **Deferred (documented):** per-request manifest TOCTOU (~20 independent
  manifest reads per Finder request — needs payload-threading refactor);
  manifest republish without lock in fetch-fundamentals/portfolio; dial
  meta into parquet attrs; sqlite connection closing + verification-import
  UNIQUE constraint.

## Test-quality lens — 8 findings, the actionable ones fixed

- **MEDIUM (fixed):** per-file serve guardrails proven bypassable (pandas
  method-call arithmetic `.add()/.div()`, `df.eval`, `np.where`, inline
  `or`-fallback) and covered only 4 of 20+ modules → new all-modules token
  walker with an explicit sanctioned allowlist (locks today's audited
  state; new violations fail).
- **MEDIUM (fixed):** `rank_in_bucket` — the ONE rank the /lab page sorts
  on — had zero behavioral tests → deliberate-twins tie-break, insufficient-
  last, dense-ranks test added.
- **LOW (fixed):** both `pytest.raises(Exception)` narrowed; mixed
  healthy+degraded loss summation pinned; conftest autouse socket guard
  (a forgotten monkeypatch can never silently hit Yahoo); dead
  serve/lenses.py + its 18 tests deleted (1,063 ≠ live-behavior count);
  config sentinel test with literal floors.
- **Deferred:** fixture-side Tool B formula copy in tests/helpers.py
  (cross-check test); healthy-control gaps in 2 Tool B exclusion tests.

## Math lenses (returned on attempt 3) — and the fixes

### option-math: 1 HIGH (fixed) + 8, 10 verified-ok
- **HIGH (fixed):** horizon-labeled option features had NO DTE-band clamp —
  `*_550d` features were computed from 162–218d expiries on CMCL/DRD/GAU/
  ORLA/TXG (mislabeled basis), and skew residuals subtracted a true-550d
  benchmark from a ~162d name. `compute_options_features` now restricts
  each horizon to its configured band (no in-band expiry → honest None);
  bands threaded from config; regression test with in-band control.
- **MEDIUM (fixed):** iv_rv_ratio compared calendar-day IV to a trading-day
  realized window ~45% too long (90d option vs ~130 calendar days of
  realized) — converted at 252/365.25 (90d → 62 trading rows).
- **MEDIUM (fixed):** the most-liquid default note claimed the sized
  contract IS the stamped expiry; the bucket-fit pick can differ —
  rephrased to "most-liquid window … (most-liquid expiry there: X)".
- **LOW (fixed):** ATM IV was one nearest contract, tie-broken to the call —
  side flips under skew injected noise into the IV-rank history. Now the
  standard put/call average at the nearest strike.
- Deferred: holiday-Thursday monthly detection (latent, no 2026 impact),
  OI-change excludes newly listed contracts + dead per-strike columns,
  config twins in option_trading defaults, iv_rank→iv_percentile naming
  (D2 milestone), 60d→90d history depth reset (one-time, documented).
- Verified OK first-hand by the agent: Black-Scholes formulas (8 stored
  deltas recomputed exactly), P&L scenario math, sizing math, skew residual
  structure, rel_spread/half_spread over all 11,302 contracts (0
  mismatches), selector determinism, LIMITED_HISTORY honesty.

### model-math: 9 findings, Tool A/B reproduced exactly
- Verified OK: Tool A betas/vol reproduced end-to-end from raw files (BTG
  exact match); Tool B layer math (margin, FCF, leverage with non-positive-
  EBITDA routing, linear forward EBITDA); prefix-sum windows ≡ legacy mask.
- **Fixed now:** Tool C fail-open (`score_eligible` defaulting True when
  the column is missing → degraded tickers silently rankable) → fails loud.
- Deferred (next session, documented): Tool D `fcf_yield` spot-basis
  unlabeled next to at-G columns (rename `fcf_yield_at_spot` + header);
  EV/EBITDA formula in two diverging copies (Tool B uncapped vs Tool D
  capped — unify in common/); >1.0-means-percent auto-divide in 5+ copies
  (extract one normalizer with a negative-rate guard); stress-ladder
  presets hardcoded; hit-rate 10% thresholds applied to log returns;
  gold-regime quantile self-inclusion (becomes leakage if Lab backtests
  against it); "52w" vol = 52 observations not 52 calendar weeks.

### lab-statistics: the JS bug, and a STRONGER null
- **MEDIUM (fixed + re-run):** v1 James-Stein used the homoscedastic
  mean(SE²) form; real SEs span 160x, so shrinkage collapsed the nowcast to
  the slow baseline in ~half the weeks (median applied factor 0.026) — the
  flagship's null could have been an artifact. Per ledger discipline, a v2
  variant (standardized heteroscedastic JS, z=gap/SE) was REGISTERED
  (n_trials now 3) and re-run with honest disjoint folds:
  **v2 VERDICT: FAILED again** — vs slow +1.06% MAE, t=1.18, 65% folds
  (20 disjoint folds; median shrink factor 0.189, so the model genuinely
  used the fast signal this time). Two independent variants failing the
  same pre-registered gate = the structural-beta conclusion is now robust,
  not an artifact.
- **MEDIUM (fixed):** gate t-stat wasn't episode-adjusted and fold label
  windows overlapped (t overstated) → fold step now test+label (disjoint
  label windows), code matches the pre-registered text.
- **MEDIUM (fixed):** contiguity guard existed only in forward_returns —
  beta_gap and conditional_dial now route through it (promoted public).
- **MEDIUM (fixed):** duplicate ticker-weeks silently double-counted and
  could mask a gap → reindex now raises on duplicates.
- **LOW/NIT (fixed):** EB prior now equal-ticker-weight (long-history
  tickers dominated it); insufficient-history cells carry NA rank (house
  rule); bucket labels state edges exactly; hit = pred×label>0. Dial
  artifact rebuilt with all of it.
- Verified OK: n_eff derivation, SE proxy form, forward label window,
  no train/test contamination, verdict JSON internally consistent
  (paired t recomputed), Wilson algebra, quantile-spread non-overlap.

## Net effect

53 findings across round-2, 28 fixed (6 commits), the rest documented
above as deferred with reasons. The flagship experiment's null verdict was
re-established under a corrected estimator and honest folds — `data/lab/
beta_gap_verdict_v2_latest.json` is the binding record (variant
483248babea7).
