"""Sync per-ticker jurisdiction tiers from the friend's Excel workbook.

Reads `Screening Data!U:U` for each row, applies math.ceil() to match the
Excel `Layer 2!C5 = ROUNDUP(VLOOKUP(...,21))` rule, and rewrites
`config/universe.yaml` in place.

Architectural note: after this script runs, `config/universe.yaml` is the
canonical Tool B jurisdiction-tier source. Any future tier change should
be made there directly (or by re-running this script with an updated
workbook). We deliberately accept that ownership rather than maintaining
a separate Tool B tier table.

Usage:
    python -m scripts.sync_universe_tiers_from_excel --dry-run
    python -m scripts.sync_universe_tiers_from_excel --apply
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import openpyxl
import yaml

from golden_vector.app.paths import ProjectPaths
from scripts.friend_excel_import import default_workbook_path, map_friend_ticker


def read_friend_tiers(workbook_path: Path) -> dict[str, int]:
    """Return {our_ticker: rounded_tier} from Screening Data!U:U.

    Skips rows where the ticker or tier cell is empty/non-numeric.
    Maps friend tickers to our universe tickers via FRIEND_TICKER_MAP.
    """
    wb = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        ws = wb["Screening Data"]
        # Header on row 1, data starts row 2; ticker is col 1, jurisdiction tier is col 21.
        out: dict[str, int] = {}
        for row in ws.iter_rows(min_row=2, values_only=True):
            ticker_cell = row[0] if row else None
            tier_cell = row[20] if row and len(row) > 20 else None
            if ticker_cell is None or tier_cell is None:
                continue
            try:
                tier_value = float(tier_cell)
            except (TypeError, ValueError):
                continue
            our_ticker = map_friend_ticker(str(ticker_cell).strip())
            out[our_ticker] = int(math.ceil(tier_value))
        return out
    finally:
        wb.close()


def load_universe_yaml(yaml_path: Path) -> list[dict]:
    text = yaml_path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    return data["tickers"]


def diff_table(current: list[dict], friend_tiers: dict[str, int]) -> list[tuple]:
    """Return [(ticker, old_tier, new_tier, in_friend, change_msg)]."""
    rows: list[tuple] = []
    for entry in current:
        ticker = entry["ticker"]
        old_tier = entry.get("jurisdiction_tier")
        new_tier = friend_tiers.get(ticker)
        in_friend = ticker in friend_tiers
        if not in_friend:
            change_msg = "(not in workbook — leave unchanged)"
        elif new_tier == old_tier:
            change_msg = "no change"
        else:
            change_msg = f"{old_tier} -> {new_tier}"
        rows.append((ticker, old_tier, new_tier, in_friend, change_msg))
    return rows


def print_diff(rows: list[tuple]) -> int:
    """Print the diff table; return count of rows that will change."""
    changes = 0
    print(f'{"Ticker":12} {"Current":>8} {"New":>6}  Notes')
    print("-" * 60)
    for ticker, old, new, in_friend, msg in rows:
        if not in_friend:
            print(f"{ticker:12} {str(old):>8} {'-':>6}  {msg}")
        else:
            marker = "*" if old != new else " "
            new_str = "-" if new is None else str(new)
            print(f"{ticker:12} {str(old):>8} {new_str:>6} {marker} {msg}")
            if old != new:
                changes += 1
    print("-" * 60)
    print(f"{changes} ticker(s) will change.")
    return changes


def apply_changes(yaml_path: Path, friend_tiers: dict[str, int]) -> int:
    """Rewrite universe.yaml in place updating jurisdiction_tier values.

    We do a line-based rewrite rather than load/dump-yaml because the file
    has comments and a particular layout we want to preserve.

    Returns the number of lines updated.
    """
    text = yaml_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=False)

    # Walk the file. State machine: when we see "  - ticker: X", remember X.
    # When we then see "    jurisdiction_tier: N", replace if friend has a value.
    current_ticker: str | None = None
    updated = 0
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- ticker:"):
            current_ticker = stripped.split(":", 1)[1].strip()
            new_lines.append(line)
            continue
        if stripped.startswith("jurisdiction_tier:") and current_ticker:
            new_tier = friend_tiers.get(current_ticker)
            if new_tier is not None:
                # Preserve indentation
                indent = line[: len(line) - len(line.lstrip())]
                old_part = stripped
                old_value = old_part.split(":", 1)[1].strip()
                if str(old_value) != str(new_tier):
                    line = f"{indent}jurisdiction_tier: {new_tier}"
                    updated += 1
            new_lines.append(line)
            continue
        new_lines.append(line)

    yaml_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes to config/universe.yaml. Default is dry-run.",
    )
    args = parser.parse_args()

    paths = ProjectPaths.discover()
    workbook = default_workbook_path(paths.repo_root)
    universe_yaml = paths.config_dir / "universe.yaml"

    if not workbook.exists():
        print(f"ERROR: workbook not found at {workbook}", file=sys.stderr)
        return 1
    if not universe_yaml.exists():
        print(f"ERROR: universe.yaml not found at {universe_yaml}", file=sys.stderr)
        return 1

    friend_tiers = read_friend_tiers(workbook)
    current = load_universe_yaml(universe_yaml)
    rows = diff_table(current, friend_tiers)
    changes = print_diff(rows)

    if not args.apply:
        print()
        print("(dry-run — re-run with --apply to write changes)")
        return 0

    if changes == 0:
        print("Nothing to change.")
        return 0

    updated = apply_changes(universe_yaml, friend_tiers)
    print(f"Wrote {updated} jurisdiction_tier line(s) to {universe_yaml}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
