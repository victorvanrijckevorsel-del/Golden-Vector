# Phase 2 review record — peer ranking

Date: 2026-06-17
Method: adversarial multi-agent workflow (4 dimensions — peer-math, benchmark-pit, snapshot-honesty,
architecture-tests — each finding independently verified). 17 agents, 12 confirmed findings (no HIGH).

## Resolutions

| # | Sev | Finding | Resolution |
|---|---|---|---|
| 1 | LOW | GDX-only filter was a contract shortcut; the plan's Codex#1 mandated benchmark-DROPPED distinct rows. A future GDX gap / GDXJ-only week would silently under-count peers (0 orphans today, so no live bias) | **Switched `compute_peer_points` to a benchmark-INDEPENDENT union cross-section** — `drop_duplicates` on (ticker, week, horizon, bucket) across ALL benchmarks. Structurally correct; identical output on current data. |
| 2 | LOW | Test never exercised the orphan case | Added `test_pool_includes_benchmark_orphan_ticker` (a GDXJ-only ticker is ranked, peer_count reflects it). |
| 3 | NIT (×3) | Singleton shipped `peer_rank_1_best=1.0` while percentile was NaN — inconsistent abstain | Null `peer_rank_1_best` where `peer_count < 2` (uniform abstain across both columns); asserted in the singleton test. |
| 4 | LOW | Peer snapshot THIN gate reused the capture per-side floor (`min_direction_effective_n`) — hidden coupling | Added dedicated `min_peer_effective_n` config knob (default 6.0); snapshot gates on it. |
| 5 | LOW | Quartile rates ship without a Wilson interval | No change — the design contract §4.3 specifies median + quartile rates with NO interval here (the significance layer is scoped to beat/alpha in §4.4); `peer_effective_n` + `THIN_PEER_POOL` already ride alongside. |
| 6 | MED | `peer_effective_n` horizon deflation never tested (all snapshot tests at h=1) | Added `test_snapshot_effective_n_deflates_by_horizon` (26 events @ h=13 → eff_n 2.0). |
| 7 | LOW | `behavior_config_hash` not asserted on persisted rows | Added `test_behavior_hash_is_stamped_on_peer_rows`. |
| 8 | LOW/NIT | No ties / NA / quartile-boundary snapshot test; caveat value unasserted | Added `test_snapshot_quartile_boundaries_and_na_exclusion` (inclusive 75/25 boundary + singleton + count≥min-but-NaN both excluded) and a `PEER_CAVEAT` value assert. |

## Outcome
- peer_points: 114,690 rows (pools 39–65, 0 singletons in real data); snapshot 519 rows (487 OK / 32 THIN).
- Union change is a no-op on current data (no orphans) but removes the latent under-count risk.
- ruff clean; peer+engine+config tests 152 green; full suite gating before commit.
