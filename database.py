"""Broadcast log — SQLite persistence for sent broadcasts.

Call :func:`initialize_database` once at startup (passing the DB path from
config) before calling any other function in this module.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# Thread-local storage ensures each thread gets its own connection.
_db_local = threading.local()

# Set by initialize_database(); all functions below rely on this being set.
_db_path: Path | None = None


def initialize_database(db_path: Path) -> None:
    """Create (or migrate) the ``broadcasts`` table and set the DB path.

    Safe to call multiple times — ``CREATE TABLE IF NOT EXISTS`` and the
    ``ALTER TABLE`` migration are idempotent.

    The function also installs a SQLite trigger that keeps the table under
    100 000 rows by automatically deleting the oldest rows after each insert.

    Args:
        db_path: Filesystem path to the SQLite database file. Created if it
            does not exist.
    """
    global _db_path
    _db_path = db_path

    try:
        conn = _get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS broadcasts (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp        DATETIME DEFAULT CURRENT_TIMESTAMP,
                sender_name      TEXT NOT NULL,
                message_content  TEXT NOT NULL,
                target_channels  TEXT NOT NULL,
                file_ids         TEXT
            )
        """)

        # Housekeeping trigger: keep the table under 100 000 rows.
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS enforce_row_limit
            AFTER INSERT ON broadcasts
            BEGIN
                DELETE FROM broadcasts WHERE id <= (NEW.id - 100000);
            END;
        """)

        # Backward-compatibility migration: add file_ids column if absent.
        cursor.execute("PRAGMA table_info(broadcasts)")
        columns = [row[1] for row in cursor.fetchall()]
        if "file_ids" not in columns:
            logger.info("Migrating database: adding 'file_ids' column.")
            cursor.execute("ALTER TABLE broadcasts ADD COLUMN file_ids TEXT")

        conn.commit()
        logger.info(f"Database initialised at {_db_path}.")
    except sqlite3.Error as exc:
        logger.error(f"Database initialisation error: {exc}")
        raise


def log_broadcast(
    sender_name: str,
    message_content: str,
    target_channels: list[str],
    file_ids: list[str] | None = None,
) -> None:
    """Persist a successful broadcast to the database.

    Args:
        sender_name: Mattermost username of the sender.
        message_content: The message body that was broadcast.
        target_channels: Display names of channels the message was sent to.
        file_ids: Mattermost file IDs of attachments that were relayed.
            ``None`` or empty list if no files were attached.
    """
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO broadcasts (sender_name, message_content, target_channels, file_ids)"
            " VALUES (?, ?, ?, ?)",
            (
                sender_name,
                message_content,
                json.dumps(target_channels),
                json.dumps(file_ids) if file_ids else None,
            ),
        )
        conn.commit()
        logger.info(f"Logged broadcast from {sender_name!r} to database.")
    except sqlite3.Error as exc:
        logger.error(f"Failed to log broadcast: {exc}")


def close_db_connection() -> None:
    """Close the database connection for the current thread.

    Called from :meth:`PostBot.on_stop` during bot shutdown.
    Safe to call even if no connection has been opened.
    """
    conn = getattr(_db_local, "conn", None)
    if conn is not None:
        conn.close()
        _db_local.conn = None
        logger.debug("Database connection closed.")


# ── Internal ──────────────────────────────────────────────────────────────────


def _get_connection() -> sqlite3.Connection:
    """Return the thread-local database connection, opening it if needed.

    Returns:
        An open :class:`sqlite3.Connection`.

    Raises:
        RuntimeError: If :func:`initialize_database` has not been called yet.
    """
    if _db_path is None:
        raise RuntimeError(
            "Database not initialised. Call initialize_database() before use."
        )
    if not hasattr(_db_local, "conn") or _db_local.conn is None:
        logger.debug(f"Opening new database connection to {_db_path}.")
        _db_local.conn = sqlite3.connect(str(_db_path), check_same_thread=False)
    return _db_local.conn
