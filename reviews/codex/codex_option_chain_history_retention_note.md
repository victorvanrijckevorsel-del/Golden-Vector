# Option-Chain History Retention Note

## Context

B3 keeps the full Yahoo option chain on every refresh. That is intentional: Yahoo only serves the current chain, and future option analytics need the full daily snapshot, not just today's selected candidates. Examples: IV skew history, open-interest and volume concentration, spread evolution, put/call ratios, and optionability tier changes.

## Current Gap

`golden_vector/app/run_pruning.py` protects artifacts referenced by retained model-state manifests and the run ids behind those artifacts. That is safe for the current coherent-state workflow, but it means old option snapshots can still erode once their model states fall outside the retained window. For normal Tool A/B/C/D current-state artifacts that is acceptable. For option chains, it is a problem because the raw chain is perishable and cannot be reconstructed later from Yahoo.

## Recommendation

Treat option-chain snapshots as a separate historical data product instead of ordinary run scratch data.

Preferred design:
- Keep the run-local snapshot for replay and manifest coherence.
- Also write an append-only option-history artifact keyed by `as_of_date`, `ticker`, and `expiration`.
- Store one partition per refresh date under a dedicated directory such as `data/history/options_chains/as_of_date=YYYY-MM-DD/`.
- Include source metadata: refresh run id, fetch status, selected/full expiry mode, source symbol, and snapshot sha256.
- Make `prune-runs` ignore this dedicated history directory by default.
- Add a separate explicit retention command later if the archive becomes too large.

Lower-effort alternative:
- Extend `prune-runs` with a protected option-snapshot policy that keeps all `data/runs/*/snapshots/options/*.parquet` files.
- This is simpler but keeps history mixed with run directories and makes old run cleanup less effective.

## Non-Goal For B3

B3 should not change candidate-selection contracts or pruning behavior. It should only parallelize the behavior-neutral full-chain fetch and flag this retention decision before we rely on historical option-chain analytics.
