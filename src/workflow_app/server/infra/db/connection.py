from __future__ import annotations

import sqlite3
from pathlib import Path

DB_TIMEOUT_S = 30.0
DB_BUSY_TIMEOUT_MS = 30000


def connect_db(root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(root / "state" / "workflow.db", timeout=DB_TIMEOUT_S)
    conn.row_factory = sqlite3.Row
    # WAL helps reduce reader/writer contention under the threaded web server.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute(f"PRAGMA busy_timeout = {DB_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
