# Hedge Readiness Progress

Baseline: `python -m pytest -q` -> 323 passed in 119.60s.

Step 1 (benchmarks config): committed in this step. Tests: 326 passed in 129.94s. Fixture smoke: n/a. Notes: Added strict benchmark config loading for GDX/GDXJ outside the Tool A/B universe.

Step 2 (options snapshot persistence): committed in this step. Tests: 329 passed in 126.23s. Fixture smoke: n/a. Notes: Added run-local options snapshot persistence and latest-options manifest pointer.

Step 3 (replay options manifest capture): committed in this step. Tests: 332 passed in 128.02s. Fixture smoke: n/a. Notes: Extended replay manifests to snapshot and verify the latest options manifest pointer.

Step 4 (options/rate/benchmark fetchers): committed in this step. Tests: 339 passed in 178.50s. Fixture smoke: yes. Notes: Added fixture-backed Yahoo options, risk-free rate, and hedge benchmark fetchers with no CLI wiring.

Step 5 (Black-Scholes math): committed in this step. Tests: 353 passed in 162.60s. Fixture smoke: n/a. Notes: Added normal CDF, signed delta, and listed-strike target-delta selection; reference call delta smoke returned 0.636831.

Step 6 (options features): committed in this step. Tests: 358 passed in 125.63s. Fixture smoke: yes. Notes: Added pure derived options features with listed-strike deltas, liquidity-gated implied move, realized vol, and optionability tier.

Step 7 (holdings loader): committed in this step. Tests: 367 passed in 222.42s. Fixture smoke: n/a. Notes: Added read-only holdings.yaml loader with strict exposure validation and no missing-file auto-create.

Step 8 (hedge math modules): committed in this step. Tests: 371 passed in 246.47s. Fixture smoke: yes. Notes: Added candidate put grid, liquidity-gated implied move, and premium-vs-downside cards; kept listed-strike delta gaps visible.
