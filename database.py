import sqlite3
import json
import threading

# Use a thread-local connection to ensure thread safety
db_connection = threading.local()

def get_db_connection():
    """Opens a new database connection if one is not already open for the current thread."""
    if not hasattr(db_connection, 'conn') or db_connection.conn is None:
        db_connection.conn = sqlite3.connect('broadcast_log.db', check_same_thread=False)
    return db_connection.conn

def initialize_database():
    """Creates the database and the 'broadcasts' table if they don't exist."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS broadcasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                sender_name TEXT NOT NULL,
                message_content TEXT NOT NULL,
                target_channels TEXT NOT NULL
            )
        ''')
        conn.commit()
        print("Database initialized successfully.")
    except sqlite3.Error as e:
        print(f"Database error during initialization: {e}")

def log_broadcast(sender_name, message_content, target_channels):
    """Logs a successful broadcast to the database."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Serialize the list of target channels into a JSON string for storage
        channels_json = json.dumps(target_channels)
        
        cursor.execute(
            "INSERT INTO broadcasts (sender_name, message_content, target_channels) VALUES (?, ?, ?)",
            (sender_name, message_content, channels_json)
        )
        conn.commit()
    except sqlite3.Error as e:
        print(f"Failed to log broadcast to database: {e}")

def close_db_connection():
    """Closes the database connection for the current thread."""
    if hasattr(db_connection, 'conn') and db_connection.conn is not None:
        db_connection.conn.close()
        db_connection.conn = None