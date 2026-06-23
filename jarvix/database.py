from __future__ import annotations

import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


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
DATABASE_PATH = Path(os.getenv("JARVIX_DATABASE", DEFAULT_DATABASE))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
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
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                room TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'offline',
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                scheduled_at TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                completed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS routines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                trigger_text TEXT NOT NULL,
                actions TEXT NOT NULL DEFAULT '[]',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS integrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'disconnected',
                display_name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

        for provider, label in (
            ("spotify", "Spotify"),
            ("youtube_music", "YouTube Music"),
            ("whatsapp", "WhatsApp Business"),
        ):
            db.execute(
                """
                INSERT OR IGNORE INTO integrations
                (provider, status, display_name, created_at)
                VALUES (?, 'disconnected', ?, ?)
                """,
                (provider, label, utc_now()),
            )


def list_rows(table: str) -> list[dict[str, Any]]:
    allowed = {"devices", "reminders", "routines", "integrations"}
    if table not in allowed:
        raise ValueError("Tabela inválida")
    with connection() as db:
        rows = db.execute(f"SELECT * FROM {table} ORDER BY id DESC").fetchall()
    return [_decode_row(dict(row)) for row in rows]


def insert_row(table: str, values: dict[str, Any]) -> dict[str, Any]:
    allowed = {"devices", "reminders", "routines"}
    if table not in allowed:
        raise ValueError("Tabela inválida")
    payload = {**values, "created_at": utc_now()}
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            payload[key] = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, bool):
            payload[key] = int(value)
    columns = ", ".join(payload)
    placeholders = ", ".join("?" for _ in payload)
    with connection() as db:
        cursor = db.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
            tuple(payload.values()),
        )
        row = db.execute(
            f"SELECT * FROM {table} WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return _decode_row(dict(row))


def update_row(table: str, row_id: int, values: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"devices", "reminders", "routines", "integrations"}
    if table not in allowed:
        raise ValueError("Tabela inválida")
    payload: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, (dict, list)):
            payload[key] = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, bool):
            payload[key] = int(value)
        else:
            payload[key] = value
    if not payload:
        return None
    assignments = ", ".join(f"{key} = ?" for key in payload)
    with connection() as db:
        db.execute(
            f"UPDATE {table} SET {assignments} WHERE id = ?",
            (*payload.values(), row_id),
        )
        row = db.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    return _decode_row(dict(row)) if row else None


def delete_row(table: str, row_id: int) -> bool:
    if table not in {"devices", "reminders", "routines"}:
        raise ValueError("Tabela inválida")
    with connection() as db:
        cursor = db.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
    return cursor.rowcount > 0


def _decode_row(row: dict[str, Any]) -> dict[str, Any]:
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
