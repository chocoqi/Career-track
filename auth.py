"""Small, local authentication helpers for Career Compass.

Passwords and recovery codes are never stored directly. The browser keeps a random
session token; SQLite only keeps its SHA-256 hash and a 14-day expiry time.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from career_data import connection


SESSION_DAYS = 14
PBKDF2_ITERATIONS = 600_000


def init_auth_db() -> None:
    with connection() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
          username TEXT PRIMARY KEY COLLATE NOCASE,
          password_hash TEXT NOT NULL, password_salt TEXT NOT NULL,
          recovery_hash TEXT NOT NULL, recovery_salt TEXT NOT NULL,
          created_at TEXT NOT NULL, password_updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS auth_sessions (
          token_hash TEXT PRIMARY KEY, username TEXT NOT NULL,
          created_at TEXT NOT NULL, expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS account_links (
          username TEXT NOT NULL, linked_username TEXT NOT NULL,
          created_at TEXT NOT NULL,
          PRIMARY KEY (username, linked_username)
        );
        """)


def _hash_secret(secret: str, salt: bytes) -> str:
    value = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt,
                                PBKDF2_ITERATIONS, dklen=32)
    return value.hex()


def _new_hash(secret: str) -> tuple[str, str]:
    salt = secrets.token_bytes(16)
    return _hash_secret(secret, salt), salt.hex()


def _new_recovery() -> tuple[str, str, str]:
    raw_code = secrets.token_hex(8).upper()
    display_code = "-".join(raw_code[i:i + 4] for i in range(0, 16, 4))
    recovery_hash, recovery_salt = _new_hash(raw_code)
    return display_code, recovery_hash, recovery_salt


def account_exists(username: str) -> bool:
    with connection() as con:
        row = con.execute("SELECT 1 FROM accounts WHERE username=?", (username,)).fetchone()
    return row is not None


def account_name(username: str) -> str | None:
    """Return the stored capitalization for a case-insensitive username."""
    with connection() as con:
        row = con.execute("SELECT username FROM accounts WHERE username=?", (username,)).fetchone()
    return row["username"] if row else None


def create_account(username: str, password: str) -> str | None:
    """Create an account and return its one-time recovery code."""
    password_hash, password_salt = _new_hash(password)
    recovery_code, recovery_hash, recovery_salt = _new_recovery()
    now = datetime.now(timezone.utc).isoformat()
    try:
        with connection() as con:
            con.execute("""INSERT INTO accounts VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (username, password_hash, password_salt, recovery_hash,
                         recovery_salt, now, now))
    except sqlite3.IntegrityError:
        return None
    return recovery_code


def verify_password(username: str, password: str) -> bool:
    with connection() as con:
        row = con.execute("SELECT password_hash, password_salt FROM accounts WHERE username=?",
                          (username,)).fetchone()
    if row is None:
        return False
    candidate = _hash_secret(password, bytes.fromhex(row["password_salt"]))
    return hmac.compare_digest(candidate, row["password_hash"])


def verify_recovery_code(username: str, recovery_code: str) -> bool:
    normalized = recovery_code.replace("-", "").replace(" ", "").upper()
    with connection() as con:
        row = con.execute("SELECT recovery_hash, recovery_salt FROM accounts WHERE username=?",
                          (username,)).fetchone()
    if row is None:
        return False
    candidate = _hash_secret(normalized, bytes.fromhex(row["recovery_salt"]))
    return hmac.compare_digest(candidate, row["recovery_hash"])


def reset_password(username: str, password: str) -> str:
    """Reset a password, invalidate sessions, and rotate the recovery code."""
    password_hash, password_salt = _new_hash(password)
    recovery_code, recovery_hash, recovery_salt = _new_recovery()
    with connection() as con:
        con.execute("""UPDATE accounts SET password_hash=?, password_salt=?, recovery_hash=?,
                       recovery_salt=?, password_updated_at=?
                       WHERE username=?""",
                    (password_hash, password_salt, recovery_hash, recovery_salt,
                     datetime.now(timezone.utc).isoformat(), username))
        con.execute("DELETE FROM auth_sessions WHERE username=?", (username,))
    return recovery_code


def delete_account(username: str) -> None:
    """Delete local account-owned records; shared legacy snapshots remain anonymous."""
    with connection() as con:
        con.execute("DELETE FROM auth_sessions WHERE username=?", (username,))
        con.execute("DELETE FROM account_links WHERE username=? OR linked_username=?",
                    (username, username))
        con.execute("DELETE FROM delivered_jobs WHERE username=?", (username,))
        con.execute("DELETE FROM subscriptions WHERE username=?", (username,))
        con.execute("DELETE FROM profiles WHERE username=?", (username,))
        con.execute("DELETE FROM snapshots WHERE username=?", (username,))
        con.execute("DELETE FROM accounts WHERE username=?", (username,))


def create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    with connection() as con:
        con.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (now.isoformat(),))
        con.execute("INSERT INTO auth_sessions VALUES (?, ?, ?, ?)",
                    (token_hash, username, now.isoformat(),
                     (now + timedelta(days=SESSION_DAYS)).isoformat()))
    return token


def session_username(token: str | None) -> str | None:
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    with connection() as con:
        row = con.execute("SELECT username, expires_at FROM auth_sessions WHERE token_hash=?",
                          (token_hash,)).fetchone()
        if row and datetime.fromisoformat(row["expires_at"]) <= now:
            con.execute("DELETE FROM auth_sessions WHERE token_hash=?", (token_hash,))
            return None
    return row["username"] if row else None


def end_session(token: str | None) -> None:
    if not token:
        return
    with connection() as con:
        con.execute("DELETE FROM auth_sessions WHERE token_hash=?",
                    (hashlib.sha256(token.encode()).hexdigest(),))


def link_accounts(username: str, linked_username: str) -> None:
    """Link both directions after the second account's password was verified."""
    now = datetime.now(timezone.utc).isoformat()
    with connection() as con:
        con.executemany("INSERT OR IGNORE INTO account_links VALUES (?, ?, ?)",
                        [(username, linked_username, now), (linked_username, username, now)])


def linked_accounts(username: str) -> list[str]:
    with connection() as con:
        rows = con.execute("SELECT linked_username FROM account_links WHERE username=? ORDER BY linked_username",
                           (username,)).fetchall()
    return [row["linked_username"] for row in rows]


init_auth_db()
