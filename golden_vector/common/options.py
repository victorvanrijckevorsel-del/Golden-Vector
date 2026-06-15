"""Shared option-market constants — one normalize boundary for contract sizing."""

from __future__ import annotations

# Standard US listed equity-option contract size: 1 contract = 100 shares. ONE copy:
# premium-spend, P&L, notional, and contracts-from-shares math across the Option
# Trading, Hedge, and Portfolio tools all scale per-contract <-> per-share by this
# single factor, so the same position can never price out differently per screen.
OPTION_CONTRACT_MULTIPLIER = 100
