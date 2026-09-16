"""Transactional access store, separate from research and portfolio data.

Codes and sessions are cryptographically random bearer credentials. SHA-256 is
appropriate here because codes have 128 bits of generated entropy; this is not
a password store and deliberately accepts no administrator-selected passwords.
"""

from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import secrets
import sqlite3
import time

SCHEMA_VERSION = 1
SESSION_SECONDS = 7 * 24 * 60 * 60
RATE_WINDOW_SECONDS = 15 * 60
EMAIL_ATTEMPTS = 10
IP_ATTEMPTS = 40
_EMAIL = re.compile(r"[^\s@<>\x00-\x1f\x7f]+@[^\s@<>\x00-\x1f\x7f]+\.[^\s@<>\x00-\x1f\x7f]+")


class RateLimited(ValueError):
    """Login budget exhausted; credentials were not checked."""


def normalize_email(value: str) -> str:
    email = value.strip().casefold()
    if len(email) > 254 or not _EMAIL.fullmatch(email):
        raise ValueError("Enter a valid email address.")
    return email


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _code_digest(value: str) -> str:
    return _digest(value.strip().replace("-", "").upper())


@dataclass(frozen=True)
class Session:
    email: str
    csrf: str
    expires_at: int


class AccessStore:
    def __init__(self, path: Path):
        self.path = path.resolve()

    @contextmanager
    def _connection(self, *, create: bool = False):
        # mode=rw fails closed if a disk goes missing; never silently creates an
        # empty access database in the live web process.
        uri = self.path.as_uri() + ("?mode=rwc" if create else "?mode=rw")
        with closing(sqlite3.connect(uri, uri=True, timeout=10)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            with connection:
                yield connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection(create=True) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise ValueError("Unsupported access database version.")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS invitations (
                    email TEXT PRIMARY KEY,
                    code_hash TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    last_login_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    email TEXT NOT NULL REFERENCES invitations(email),
                    csrf TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_email ON sessions(email);
                CREATE TABLE IF NOT EXISTS login_limits (
                    key_hash TEXT PRIMARY KEY,
                    attempts INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                PRAGMA user_version=1;
            """)
        self.path.chmod(0o600)

    def check(self) -> None:
        with self._connection() as connection:
            if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                raise ValueError("Initialize the access database before starting the website.")
            connection.execute("SELECT email FROM invitations LIMIT 1").fetchall()
            connection.execute("SELECT token_hash FROM sessions LIMIT 1").fetchall()
            connection.execute("SELECT key_hash FROM login_limits LIMIT 1").fetchall()

    def issue(self, email: str, *, days: int = 90, now: int | None = None) -> str:
        email = normalize_email(email)
        if not 1 <= days <= 3650:
            raise ValueError("Invitation lifetime must be between 1 and 3650 days.")
        instant = int(time.time()) if now is None else now
        raw = secrets.token_hex(16).upper()
        code = "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM sessions WHERE email=?", (email,))
            connection.execute(
                """INSERT INTO invitations(email,code_hash,created_at,expires_at,revoked)
                VALUES(?,?,?,?,0) ON CONFLICT(email) DO UPDATE SET
                code_hash=excluded.code_hash, created_at=excluded.created_at,
                expires_at=excluded.expires_at, revoked=0, last_login_at=NULL""",
                (email, _code_digest(code), instant, instant + days * 86400),
            )
        return code

    def revoke(self, email: str) -> bool:
        email = normalize_email(email)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM sessions WHERE email=?", (email,))
            result = connection.execute("UPDATE invitations SET revoked=1 WHERE email=?", (email,))
            return result.rowcount > 0

    def invitations(self) -> list[dict]:
        with self._connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT email,created_at,expires_at,revoked,last_login_at FROM invitations ORDER BY email"
            )]

    def _reserve_attempt(self, email: str, address: str, instant: int) -> None:
        limited = False
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM login_limits WHERE expires_at<=?", (instant,))
            connection.execute("DELETE FROM sessions WHERE expires_at<=?", (instant,))
            for kind, value, budget in (("email", email, EMAIL_ATTEMPTS), ("ip", address, IP_ATTEMPTS)):
                key = _digest(f"{kind}:{value}")
                connection.execute(
                    """INSERT INTO login_limits VALUES(?,1,?)
                    ON CONFLICT(key_hash) DO UPDATE SET attempts=attempts+1""",
                    (key, instant + RATE_WINDOW_SECONDS),
                )
                attempts = connection.execute(
                    "SELECT attempts FROM login_limits WHERE key_hash=?", (key,)
                ).fetchone()[0]
                limited |= attempts > budget
        # Commit counters even when rejecting; budgets apply across processes.
        if limited:
            raise RateLimited("Too many attempts. Please try again in 15 minutes.")

    def login(self, email: str, code: str, address: str, *, now: int | None = None) -> str | None:
        instant = int(time.time()) if now is None else now
        canonical = email.strip().casefold()[:254]
        self._reserve_attempt(canonical, address[:128], instant)
        try:
            email = normalize_email(email)
        except ValueError:
            return None
        if len(code) > 128:
            return None
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM invitations WHERE email=?", (email,)).fetchone()
            valid_code = secrets.compare_digest(_code_digest(code), row["code_hash"] if row else "0" * 64)
            if row is None or not valid_code or row["revoked"] or row["expires_at"] <= instant:
                return None
            token = secrets.token_urlsafe(32)
            connection.execute("INSERT INTO sessions VALUES(?,?,?,?)", (
                _digest(token), email, secrets.token_urlsafe(32),
                min(instant + SESSION_SECONDS, row["expires_at"]),
            ))
            connection.execute("UPDATE invitations SET last_login_at=? WHERE email=?", (instant, email))
            return token

    def session(self, token: str, *, now: int | None = None) -> Session | None:
        if not token or len(token) > 128:
            return None
        instant = int(time.time()) if now is None else now
        with self._connection() as connection:
            row = connection.execute(
                """SELECT s.email,s.csrf,s.expires_at FROM sessions s
                JOIN invitations i ON s.email=i.email
                WHERE s.token_hash=? AND s.expires_at>? AND i.expires_at>? AND i.revoked=0""",
                (_digest(token), instant, instant),
            ).fetchone()
        return Session(**dict(row)) if row else None

    def logout(self, token: str) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash=?", (_digest(token),))
