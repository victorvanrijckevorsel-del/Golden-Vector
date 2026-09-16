"""Local/SSH administration: python -m golden_vector.access --help."""

import argparse
from datetime import UTC, datetime
from pathlib import Path

from golden_vector.access.store import AccessStore
from golden_vector.app.paths import ProjectPaths


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Manage Golden Vector website invitations.")
    parser.add_argument("--database", type=Path, default=ProjectPaths.discover().data_dir / "access" / "access.sqlite3")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Initialize the separate access database.")
    invite = commands.add_parser("invite", help="Create or replace a code; previous sessions are revoked.")
    invite.add_argument("--email", required=True)
    invite.add_argument("--days", type=int, default=90)
    revoke = commands.add_parser("revoke", help="Immediately revoke a code and all its sessions.")
    revoke.add_argument("--email", required=True)
    commands.add_parser("list", help="List invitees without exposing credentials.")
    args = parser.parse_args(argv)
    store = AccessStore(args.database)
    if args.command == "init":
        store.initialize()
        print("Access database ready.")
    elif args.command == "invite":
        code = store.issue(args.email, days=args.days)
        print(f"Email: {args.email.strip().casefold()}\nCode: {code}\nValid for {args.days} days.\n"
              "Share this code privately with the invitee. It cannot be retrieved later.")
    elif args.command == "revoke":
        print("Access revoked." if store.revoke(args.email) else "No invitation found.")
    else:
        for row in store.invitations():
            expiry = datetime.fromtimestamp(row["expires_at"], UTC).isoformat()
            status = "revoked" if row["revoked"] else "active" if row["expires_at"] > datetime.now(UTC).timestamp() else "expired"
            print(f"{row['email']}\t{status}\texpires {expiry}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
