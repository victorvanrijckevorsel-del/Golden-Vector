"""Regenerate the dial GDX-13w golden parity fixture.

Run this ONLY to intentionally bless a reviewed output change:
    python -m tests.tools.regen_dial_golden

The golden is otherwise frozen; the parity test in
``tests/test_lab_dial_panel_parity.py`` asserts the live build matches it.
"""

from __future__ import annotations

from golden_vector.lab.conditional_dial import build_dial_table
from tests.test_lab_dial_panel_parity import (
    GOLDEN_PATH,
    PARITY_HORIZON,
    PARITY_MIN_EFF_N,
    parity_weekly_frame,
)


def main() -> None:
    table = build_dial_table(
        parity_weekly_frame(),
        horizon_weeks=PARITY_HORIZON,
        min_effective_n=PARITY_MIN_EFF_N,
    ).reset_index(drop=True)
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(GOLDEN_PATH, index=False)
    print(f"wrote {GOLDEN_PATH}: {len(table)} rows, cols={list(table.columns)}")


if __name__ == "__main__":
    main()
