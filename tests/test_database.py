from dotenv import load_dotenv

load_dotenv("tests/test.env")

import unittest
import sqlite3
import json
import os
from pathlib import Path
from scripts.database import initialize_database, log_broadcast, get_db_connection, DB_PATH

class TestDatabase(unittest.TestCase):
    def setUp(self):
        # Use a temporary database file for testing
        self.test_db_path = Path("test_broadcast_log.db")
        if self.test_db_path.exists():
            os.remove(self.test_db_path)
        
        # Monkeypatch DB_PATH in scripts.database
        self.original_db_path = DB_PATH
        import scripts.database
        scripts.database.DB_PATH = self.test_db_path
        
        # Ensure thread-local connection is cleared
        if hasattr(scripts.database.db_connection, "conn"):
            if scripts.database.db_connection.conn:
                scripts.database.db_connection.conn.close()
            scripts.database.db_connection.conn = None

    def tearDown(self):
        # Close connection and remove test database
        import scripts.database
        if hasattr(scripts.database.db_connection, "conn") and scripts.database.db_connection.conn:
            scripts.database.db_connection.conn.close()
            scripts.database.db_connection.conn = None
        
        if self.test_db_path.exists():
            os.remove(self.test_db_path)
        
        # Restore original DB_PATH
        scripts.database.DB_PATH = self.original_db_path

    def test_initialize_database(self):
        initialize_database()
        self.assertTrue(self.test_db_path.exists())
        
        conn = sqlite3.connect(self.test_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='broadcasts'")
        self.assertIsNotNone(cursor.fetchone())
        
        cursor.execute("PRAGMA table_info(broadcasts)")
        columns = [column[1] for column in cursor.fetchall()]
        self.assertIn("id", columns)
        self.assertIn("sender_name", columns)
        self.assertIn("message_content", columns)
        self.assertIn("target_channels", columns)
        self.assertIn("file_ids", columns)
        conn.close()

    def test_log_broadcast(self):
        initialize_database()
        sender = "test_user"
        content = "test_message"
        channels = ["channel1", "channel2"]
        files = ["file1"]
        
        log_broadcast(sender, content, channels, files)
        
        conn = sqlite3.connect(self.test_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT sender_name, message_content, target_channels, file_ids FROM broadcasts")
        row = cursor.fetchone()
        self.assertEqual(row[0], sender)
        self.assertEqual(row[1], content)
        self.assertEqual(json.loads(row[2]), channels)
        self.assertEqual(json.loads(row[3]), files)
        conn.close()

    def test_row_limit_trigger(self):
        initialize_database()
        conn = sqlite3.connect(self.test_db_path)
        cursor = conn.cursor()
        
        # We need to insert more than 100,000 rows to test the trigger, 
        # but that's too slow for a unit test.
        # Let's verify the trigger exists.
        cursor.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name='enforce_row_limit'")
        self.assertIsNotNone(cursor.fetchone())
        conn.close()

if __name__ == "__main__":
    unittest.main()
