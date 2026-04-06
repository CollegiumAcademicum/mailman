import json
import sqlite3
import sys
import os
from pathlib import Path

import pytest

# Ensure the postbot package root is on the path so `import database` works.
sys.path.insert(0, str(Path(__file__).parent.parent))

import database
from database import (
    initialize_database,
    log_broadcast,
    close_db_connection,
)


@pytest.fixture(autouse=True)
def reset_db():
    """Reset module-level database state before every test."""
    close_db_connection()
    database._db_path = None
    if hasattr(database._db_local, "conn"):
        database._db_local.conn = None
    yield
    # Cleanup after test as well
    close_db_connection()
    database._db_path = None
    if hasattr(database._db_local, "conn"):
        database._db_local.conn = None


def test_initialize_creates_file(tmp_path):
    db_file = tmp_path / "test.db"
    initialize_database(db_file)
    assert db_file.exists()


def test_initialize_creates_broadcasts_table(tmp_path):
    db_file = tmp_path / "test.db"
    initialize_database(db_file)

    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='broadcasts'"
        )
        assert cursor.fetchone() is not None

        cursor.execute("PRAGMA table_info(broadcasts)")
        columns = [row[1] for row in cursor.fetchall()]
        for col in ("id", "timestamp", "sender_name", "message_content", "target_channels", "file_ids"):
            assert col in columns
    finally:
        conn.close()


def test_initialize_creates_trigger(tmp_path):
    db_file = tmp_path / "test.db"
    initialize_database(db_file)

    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name='enforce_row_limit'"
        )
        assert cursor.fetchone() is not None
    finally:
        conn.close()


def test_initialize_idempotent(tmp_path):
    db_file = tmp_path / "test.db"
    initialize_database(db_file)
    # Should not raise — CREATE IF NOT EXISTS is idempotent
    initialize_database(db_file)


def test_log_broadcast_stores_data(tmp_path):
    db_file = tmp_path / "test.db"
    initialize_database(db_file)
    log_broadcast("alice", "hello world", ["Channel A", "Channel B"])

    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT sender_name, message_content, target_channels, file_ids FROM broadcasts"
        )
        row = cursor.fetchone()
        assert row is not None
        sender_name, message_content, target_channels, file_ids = row
        assert sender_name == "alice"
        assert message_content == "hello world"
        assert json.loads(target_channels) == ["Channel A", "Channel B"]
        assert file_ids is None
    finally:
        conn.close()


def test_log_broadcast_with_files(tmp_path):
    db_file = tmp_path / "test.db"
    initialize_database(db_file)
    log_broadcast("bob", "msg", ["ch"], file_ids=["file_1", "file_2"])

    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT file_ids FROM broadcasts")
        row = cursor.fetchone()
        assert row is not None
        assert json.loads(row[0]) == ["file_1", "file_2"]
    finally:
        conn.close()


def test_log_broadcast_multiple_rows(tmp_path):
    db_file = tmp_path / "test.db"
    initialize_database(db_file)
    log_broadcast("user1", "first", ["ch1"])
    log_broadcast("user2", "second", ["ch2"])
    log_broadcast("user3", "third", ["ch3"])

    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM broadcasts")
        count = cursor.fetchone()[0]
        assert count == 3
    finally:
        conn.close()


def test_get_connection_before_init_raises():
    # _db_path is None thanks to the autouse fixture
    with pytest.raises(RuntimeError, match="not initialised"):
        database._get_connection()


def test_close_db_connection_safe_before_open():
    # Should be a no-op — must not raise
    close_db_connection()


def test_initialize_migration_adds_file_ids(tmp_path):
    db_file = tmp_path / "old.db"

    # Create the database with the original schema (no file_ids column)
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "CREATE TABLE broadcasts ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, "
        "sender_name TEXT NOT NULL, "
        "message_content TEXT NOT NULL, "
        "target_channels TEXT NOT NULL"
        ")"
    )
    conn.commit()
    conn.close()

    initialize_database(db_file)

    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(broadcasts)")
        columns = [row[1] for row in cursor.fetchall()]
        assert "file_ids" in columns
    finally:
        conn.close()
