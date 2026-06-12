# Program A — Backtest Results (2026-06-12)

All five backtest experiments ran on live data with the pre-registered,
binding gates. **Every backtestable Tool A / Tool C ranking is SUPPORTED.**
Survivor-only universe → capped at SUPPORTED (not VALIDATED) per the spec.

| Experiment | Claim tested | Verdict | Key numbers |
|---|---|---|---|
| **E1a** | Tool A Δ Core gearing rank is stable out of sample | **SUPPORTED** | stability IC 0.61 (~reliability ceiling), 98% of 43 fold-pairs ≥ 0.30 |
| **E1b** | Tool A Δ Core rank forward-predicts realized gold beta | **SUPPORTED** | IC 0.48, NW-t 18.3, 100% of 44 folds positive, tercile spread 1.11β; beats single-12M & trailing-beta baselines |
| **E2** | Down-beta rank predicts down-beta in future gold-down weeks | **SUPPORTED** | IC 0.155, NW-t 6.8, 83% folds, tercile spread 0.58β (t=3.4) |
| **E3** | Tool C downside rank = most fragile when gold falls (orientation pinned) | **SUPPORTED** | directed IC 0.22, NW-t 8.6, 97% of 35 folds, spread t=7.9; beats down-beta-only baseline |
| **E3b** | Tool C upside rank = most upside capture when gold rises | **SUPPORTED** | directed IC 0.17, NW-t 4.1, 81% of 36 folds, spread t=4.1 |

## What this means (plainly)

The rankings the product shows — gold sensitivity, downside resilience,
upside capture — **genuinely hold up out of sample, walk-forward, against
binding gates set before any number was seen.** And the multi-component Tool C
composites beat their single-component baselines (the extra machinery earns
its place). E1b independently agrees with the earlier beta-gap experiment
(Tool A's structural betas are near-optimal).

## Honesty notes carried onto every card

- **SUPPORTED, not VALIDATED**: survivor-only (today's 62 names; no
  dead-miner records). Upper bound on what a contemporaneous investor saw.
- **Code-vintage**: the structural panel is data-PIT but regenerated with
  2026 code/config/universe.
- **E3/E3b outcome is noisy**: per-week down/up-capture split-half ceiling is
  low (0.08–0.09) — the cross-sectional signal survives the noise across
  35–36 disjoint folds, which is why the gates pass; the magnitude is
  reported descriptively, not as evidence of large effect sizes.
- **No leak**: the time-reversal canary shows honest 0.48 vs contaminated
  1.00 (ΔIC 0.52); Tool C reconstruction reproduces the live artifact exactly
  (parity 54/54, max|diff|=0).

## Provenance

Variants registered in `data/lab/variant_ledger.jsonl` BEFORE compute
(validation_e1a/e1b/e2/e3/e3b). Engine: `golden_vector/lab/validation.py`.
19 tests incl. parity (Tool A cores + Tool C scores), sign canaries,
time-reversal contrast, ledger-drift guard. Codex reviewed chunk 1
(READY WITH CHANGES → all addressed).

## Remaining before the Scorecard ships

E4 forward-accrual protocol (Tool B/D/options — first verdicts ~2031);
persistence (run-stamped `scorecard_latest.parquet` + meta); the `/scorecard`
page (render-only, guardrailed). Then a verification fleet over the complete
engine before any verdict is published.
