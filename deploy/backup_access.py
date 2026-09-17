"""Make a private, consistent SQLite backup; source remains open and unchanged."""
import argparse
import os
from pathlib import Path
import sqlite3


def backup_access(source: Path, destination: Path) -> None:
    source, destination = source.resolve(strict=True), destination.resolve()
    # Create exclusively with private permissions before SQLite opens it.
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
        with sqlite3.connect(destination) as output:
            original.backup(output)
            if output.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Access backup failed integrity check")
    print("Consistent private access backup created; no credentials printed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    backup_access(args.source, args.destination)
