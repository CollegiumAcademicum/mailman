import sqlite3
import json
import logging
import threading
import os
from scripts.config import DB_PATH

# Use a thread-local connection to ensure thread safety
db_connection = threading.local()


def get_db_connection():
    """Opens a new database connection if one is not already open for the current thread."""
    if not hasattr(db_connection, "conn") or db_connection.conn is None:
        logging.debug("Creating new database connection for thread.")
        db_connection.conn = sqlite3.connect(
                str(DB_PATH), check_same_thread=False
        )
    return db_connection.conn


def initialize_database():
    """Creates or updates the 'broadcasts' table to include a 'file_ids' column."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('PRAGMA auto_vacuum = FULL;')
        cursor.execute('VACUUM;')

        # Create table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS broadcasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                sender_name TEXT NOT NULL,
                message_content TEXT NOT NULL,
                target_channels TEXT NOT NULL,
                file_ids TEXT
            )
        """)

        # automatic housekeeping to limit the amount of database rows
        cursor.execute(
            '''
            CREATE TRIGGER IF NOT EXISTS enforce_row_limit
                AFTER INSERT
                ON broadcasts
            BEGIN
                -- Deletes rows older than the current ID minus 100,000
                DELETE FROM broadcasts WHERE id <= (NEW.id - 100000);
            END;
                       '''
            )


        # Add the file_ids column if it doesn't exist (for backward compatibility)
        cursor.execute("PRAGMA table_info(broadcasts)")
        columns = [column[1] for column in cursor.fetchall()]
        if "file_ids" not in columns:
            logging.info("Adding 'file_ids' column to 'broadcasts' table.")
            cursor.execute("ALTER TABLE broadcasts ADD COLUMN file_ids TEXT")

        conn.commit()
        if DB_PATH.exists():
            logging.info(f"Database initialized successfully.")
        else:
            logging.warning("Database initialization failed.")
    except sqlite3.Error as e:
        logging.error(f"Database error during initialization: {e}")


def log_broadcast(sender_name, message_content, target_channels, file_ids=None):
    """Logs a successful broadcast to the database."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        channels_json = json.dumps(target_channels)
        files_json = json.dumps(file_ids) if file_ids else None

        cursor.execute(
            "INSERT INTO broadcasts (sender_name, message_content, target_channels, file_ids) VALUES (?, ?, ?, ?)",
            (sender_name, message_content, channels_json, files_json),
        )
        conn.commit()
        logging.info(f"Logged broadcast from {sender_name} to database.")
    except sqlite3.Error as e:
        logging.error(f"Failed to log broadcast to database: {e}")


def close_db_connection():
    """Closes the database connection for the current thread."""
    if hasattr(db_connection, "conn") and db_connection.conn is not None:
        logging.debug("Closing database connection for thread.")
        db_connection.conn.close()
        db_connection.conn = None
