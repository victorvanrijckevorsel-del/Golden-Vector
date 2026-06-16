"""Centralized required-column contract for persisted option feature snapshots.

Kept minimal-but-meaningful (audit M11): only columns guaranteed present in EVERY
feature row -- empty/non-optionable tickers included -- so a read fails loud on a
corrupt or wrong-file input without over-tightening on optional, config-driven
columns (the horizon-suffixed IV/skew fields).

Raw option-chain snapshots are intentionally NOT column-contracted here: empty/
non-optionable chains (most of the universe) carry only identity + ``empty_reason``
while non-empty chains carry the full detail set, so the only universal column is
``ticker``. Chain reads are guarded by sha256 instead.
"""

from __future__ import annotations

# Stable base of every options feature row the artifact builder consumes. Horizon-
# suffixed columns (atm_iv_*d, put_iv_25d_*d, ...) are config-driven and stay optional.
# optionability_tier gates candidate building; underlying_price drives pricing -- a
# feature file missing either would silently drop the ticker, so fail loud instead.
OPTIONS_FEATURE_REQUIRED_COLUMNS: tuple[str, ...] = (
    "ticker",
    "optionability_tier",
    "underlying_price",
)
