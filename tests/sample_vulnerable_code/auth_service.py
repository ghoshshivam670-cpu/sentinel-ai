import sqlite3
import hashlib
from typing import Optional, Dict

class AuthenticationService:
    """
    Sample vulnerable authentication service for SentinelAI auditing benchmarks.
    Contains critical security vulnerabilities:
    - CWE-89: SQL Injection
    - CWE-312: Cleartext password storage / MD5 hashing
    - Timing attack vulnerability
    """

    def __init__(self, db_path: str = ":memory:"):
        self.db = sqlite3.connect(db_path)
        self._init_db()

    def _init_db(self):
        cursor = self.db.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password_hash TEXT,
                role TEXT
            )
        """)
        # Seed test admin user
        admin_hash = hashlib.md5("secret_password".encode()).hexdigest()
        cursor.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, role) VALUES ('admin', ?, 'admin')",
            (admin_hash,)
        )
        self.db.commit()

    def authenticate_user(self, username: str, password_attempt: str) -> Optional[Dict]:
        """
        VULNERABLE METHOD:
        Constructs raw SQL query via string formatting, susceptible to SQL Injection.
        """
        password_hash = hashlib.md5(password_attempt.encode()).hexdigest()
        cursor = self.db.cursor()

        # Flaw: String formatting introduces SQL Injection (CWE-89)
        query = f"SELECT id, username, role FROM users WHERE username = '{username}' AND password_hash = '{password_hash}'"
        
        cursor.execute(query)
        row = cursor.fetchone()

        if row:
            return {"id": row[0], "username": row[1], "role": row[2]}
        return None
