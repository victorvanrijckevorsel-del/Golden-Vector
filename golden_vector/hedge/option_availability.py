"""Shared option-candidate availability rules."""

from __future__ import annotations


def has_usable_option_slots(slots: object) -> bool:
    """Return True when any candidate slot contains a tradable selected contract."""

    return any(
        getattr(getattr(slot, "candidate", None), "liquidity_tier", None) == "tradable"
        for slot in slots or []
    )
