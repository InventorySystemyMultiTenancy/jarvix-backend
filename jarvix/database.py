from __future__ import annotations

import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - optional in local SQLite mode
    psycopg = None
    dict_row = None


ROOT = Path(__file__).resolve().parent.parent
if getattr(sys, "frozen", False):
    DEFAULT_DATABASE = (
        Path(os.getenv("LOCALAPPDATA", Path.home()))
        / "Jarvix"
        / "data"
        / "jarvix.db"
    )
else:
    DEFAULT_DATABASE = ROOT / "data" / "jarvix.db"

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("JARVIX_DATABASE_URL", "")
DATABASE_PATH = Path(os.getenv("JARVIX_DATABASE", DEFAULT_DATABASE))
IS_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))


TENANT_TABLES = {"devices", "reminders", "routines", "integrations", "media_library"}
WRITABLE_TABLES = {"devices", "reminders", "routines", "media_library"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def placeholder(index: int = 1) -> str:
    return "%s" if IS_POSTGRES else "?"


def placeholders(count: int) -> str:
    return ", ".join(placeholder(i) for i in range(count))


def normalize_email(email: str) -> str:
    return email.strip().lower()


@contextmanager
def connection() -> Iterator[Any]:
    if IS_POSTGRES:
        if psycopg is None:
            raise RuntimeError("Instale psycopg[binary] para usar PostgreSQL.")
        db = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    else:
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(DATABASE_PATH)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")

    try:
        yield db
        db.commit()
    finally:
        db.close()


def initialize() -> None:
    with connection() as db:
        if IS_POSTGRES:
            _initialize_postgres(db)
        else:
            _initialize_sqlite(db)


def _initialize_sqlite(db: Any) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            room TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'offline',
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            scheduled_at TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            completed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS routines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            trigger_text TEXT NOT NULL,
            actions TEXT NOT NULL DEFAULT '[]',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS integrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'disconnected',
            display_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, provider)
        );

        CREATE TABLE IF NOT EXISTS media_library (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            artist TEXT NOT NULL DEFAULT '',
            album TEXT NOT NULL DEFAULT '',
            provider TEXT NOT NULL DEFAULT 'youtube_music',
            media_type TEXT NOT NULL DEFAULT 'music',
            created_at TEXT NOT NULL
        );
        """
    )
    for table in TENANT_TABLES:
        _ensure_sqlite_column(db, table, "user_id", "INTEGER REFERENCES users(id) ON DELETE CASCADE")


def _initialize_postgres(db: Any) -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS devices (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            room TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'offline',
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS reminders (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            scheduled_at TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            completed BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS routines (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            trigger_text TEXT NOT NULL,
            actions TEXT NOT NULL DEFAULT '[]',
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS integrations (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'disconnected',
            display_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, provider)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS media_library (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            artist TEXT NOT NULL DEFAULT '',
            album TEXT NOT NULL DEFAULT '',
            provider TEXT NOT NULL DEFAULT 'youtube_music',
            media_type TEXT NOT NULL DEFAULT 'music',
            created_at TEXT NOT NULL
        )
        """,
    ]
    for statement in statements:
        db.execute(statement)


def _ensure_sqlite_column(db: Any, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def create_user(name: str, email: str, password_hash: str) -> dict[str, Any]:
    payload = {
        "name": name.strip(),
        "email": normalize_email(email),
        "password_hash": password_hash,
        "created_at": utc_now(),
    }
    with connection() as db:
        if IS_POSTGRES:
            row = db.execute(
                """
                INSERT INTO users (name, email, password_hash, created_at)
                VALUES (%s, %s, %s, %s)
                RETURNING id, name, email, created_at
                """,
                tuple(payload.values()),
            ).fetchone()
        else:
            cursor = db.execute(
                """
                INSERT INTO users (name, email, password_hash, created_at)
                VALUES (?, ?, ?, ?)
                """,
                tuple(payload.values()),
            )
            row = db.execute(
                "SELECT id, name, email, created_at FROM users WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
    user = dict(row)
    ensure_default_integrations(int(user["id"]))
    return user


def find_user_by_email(email: str) -> dict[str, Any] | None:
    with connection() as db:
        row = db.execute(
            f"SELECT * FROM users WHERE email = {placeholder()}",
            (normalize_email(email),),
        ).fetchone()
    return dict(row) if row else None


def find_user_by_id(user_id: int) -> dict[str, Any] | None:
    with connection() as db:
        row = db.execute(
            f"SELECT id, name, email, created_at FROM users WHERE id = {placeholder()}",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def ensure_default_integrations(user_id: int) -> None:
    with connection() as db:
        for provider, label in (
            ("spotify", "Spotify"),
            ("youtube_music", "YouTube Music"),
            ("whatsapp", "WhatsApp Business"),
        ):
            if IS_POSTGRES:
                db.execute(
                    """
                    INSERT INTO integrations
                    (user_id, provider, status, display_name, created_at)
                    VALUES (%s, %s, 'disconnected', %s, %s)
                    ON CONFLICT (user_id, provider) DO NOTHING
                    """,
                    (user_id, provider, label, utc_now()),
                )
            else:
                db.execute(
                    """
                    INSERT OR IGNORE INTO integrations
                    (user_id, provider, status, display_name, created_at)
                    VALUES (?, ?, 'disconnected', ?, ?)
                    """,
                    (user_id, provider, label, utc_now()),
                )


def list_rows(table: str, user_id: int) -> list[dict[str, Any]]:
    if table not in TENANT_TABLES:
        raise ValueError("Tabela inválida")
    ensure_default_integrations(user_id)
    with connection() as db:
        rows = db.execute(
            f"SELECT * FROM {table} WHERE user_id = {placeholder()} ORDER BY id DESC",
            (user_id,),
        ).fetchall()
    return [_decode_row(dict(row)) for row in rows]


def insert_row(table: str, values: dict[str, Any], user_id: int) -> dict[str, Any]:
    if table not in WRITABLE_TABLES:
        raise ValueError("Tabela inválida")
    payload = {**values, "user_id": user_id, "created_at": utc_now()}
    payload = _encode_payload(payload)
    columns = ", ".join(payload)
    if IS_POSTGRES:
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders(len(payload))}) RETURNING *"
        with connection() as db:
            row = db.execute(sql, tuple(payload.values())).fetchone()
    else:
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders(len(payload))})"
        with connection() as db:
            cursor = db.execute(sql, tuple(payload.values()))
            row = db.execute(
                f"SELECT * FROM {table} WHERE id = ? AND user_id = ?",
                (cursor.lastrowid, user_id),
            ).fetchone()
    return _decode_row(dict(row))


def update_row(
    table: str, row_id: int, values: dict[str, Any], user_id: int
) -> dict[str, Any] | None:
    allowed = {"devices", "reminders", "routines", "integrations"}
    if table not in allowed:
        raise ValueError("Tabela inválida")
    payload = _encode_payload(values)
    payload.pop("id", None)
    payload.pop("user_id", None)
    if not payload:
        return None

    assignments = ", ".join(f"{key} = {placeholder()}" for key in payload)
    params = (*payload.values(), row_id, user_id)
    with connection() as db:
        if IS_POSTGRES:
            row = db.execute(
                f"""
                UPDATE {table}
                SET {assignments}
                WHERE id = %s AND user_id = %s
                RETURNING *
                """,
                params,
            ).fetchone()
        else:
            db.execute(
                f"UPDATE {table} SET {assignments} WHERE id = ? AND user_id = ?",
                params,
            )
            row = db.execute(
                f"SELECT * FROM {table} WHERE id = ? AND user_id = ?",
                (row_id, user_id),
            ).fetchone()
    return _decode_row(dict(row)) if row else None


def delete_row(table: str, row_id: int, user_id: int) -> bool:
    if table not in WRITABLE_TABLES:
        raise ValueError("Tabela inválida")
    with connection() as db:
        cursor = db.execute(
            f"DELETE FROM {table} WHERE id = {placeholder()} AND user_id = {placeholder()}",
            (row_id, user_id),
        )
    return cursor.rowcount > 0


def _encode_payload(values: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, (dict, list)):
            payload[key] = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, bool) and not IS_POSTGRES:
            payload[key] = int(value)
        else:
            payload[key] = value
    return payload


def _decode_row(row: dict[str, Any]) -> dict[str, Any]:
    row.pop("user_id", None)
    for field in ("metadata", "actions"):
        if field in row:
            try:
                row[field] = json.loads(row[field])
            except (TypeError, json.JSONDecodeError):
                pass
    for field in ("completed", "enabled"):
        if field in row:
            row[field] = bool(row[field])
    return row
