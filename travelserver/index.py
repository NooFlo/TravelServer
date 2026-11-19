import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    name TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    sha256 TEXT NOT NULL,
    source TEXT NOT NULL,
    backup_date TEXT NOT NULL,
    backed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (sha256, source)
);
"""


class BackupIndex:
    def __init__(self, primary_dir, mirror_dir=None):
        os.makedirs(primary_dir, exist_ok=True)
        if mirror_dir:
            os.makedirs(mirror_dir, exist_ok=True)
        self.primary = os.path.join(primary_dir, "index.db")
        self.mirror = os.path.join(mirror_dir, "index.db") if mirror_dir else None
        self._init_db(self.primary)
        if self.mirror:
            self._init_db(self.mirror)

    def _connect(self, path):
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self, path):
        with self._connect(path) as conn:
            conn.executescript(SCHEMA)

    def find(self, name, size):
        with self._connect(self.primary) as conn:
            rows = conn.execute(
                "SELECT sha256, source, backup_date FROM files WHERE name=? AND size=?",
                (name, size),
            ).fetchall()
        return rows

    def find_hash(self, sha256):
        with self._connect(self.primary) as conn:
            return conn.execute(
                "SELECT name, source, backup_date FROM files WHERE sha256=?", (sha256,)
            ).fetchone()

    def add(self, name, size, mtime, sha256, source, backup_date):
        for path in [self.primary] + ([self.mirror] if self.mirror else []):
            with self._connect(path) as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO files (name, size, mtime, sha256, source, backup_date) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (name, size, mtime, sha256, source, backup_date),
                )
