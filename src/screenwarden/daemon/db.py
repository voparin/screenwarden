import sqlite3
from datetime import date, datetime
from typing import Optional


class Database:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def init_schema(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY,
                user TEXT NOT NULL,
                started_at DATETIME NOT NULL,
                ended_at DATETIME,
                duration_seconds INTEGER
            );
            CREATE TABLE IF NOT EXISTS daily_usage (
                id INTEGER PRIMARY KEY,
                user TEXT NOT NULL,
                date DATE NOT NULL,
                total_seconds INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user, date)
            );
            CREATE TABLE IF NOT EXISTS time_grants (
                id INTEGER PRIMARY KEY,
                user TEXT NOT NULL,
                granted_at DATETIME NOT NULL,
                extra_seconds INTEGER NOT NULL,
                reason TEXT,
                processed INTEGER NOT NULL DEFAULT 0
            );
        """)
        self._conn.commit()

    def record_session_start(self, user: str, started_at: datetime) -> int:
        cur = self._conn.execute(
            "INSERT INTO sessions (user, started_at) VALUES (?, ?)",
            (user, started_at.isoformat()),
        )
        self._conn.commit()
        return cur.lastrowid

    def record_session_end(self, session_id: int, ended_at: datetime):
        self._conn.execute(
            """UPDATE sessions
               SET ended_at = ?,
                   duration_seconds = CAST(
                       (julianday(?) - julianday(started_at)) * 86400 AS INTEGER
                   )
               WHERE id = ?""",
            (ended_at.isoformat(), ended_at.isoformat(), session_id),
        )
        self._conn.commit()

    def add_usage_seconds(self, user: str, day: date, seconds: int):
        self._conn.execute(
            """INSERT INTO daily_usage (user, date, total_seconds)
               VALUES (?, ?, ?)
               ON CONFLICT(user, date)
               DO UPDATE SET total_seconds = total_seconds + excluded.total_seconds""",
            (user, day.isoformat(), seconds),
        )
        self._conn.commit()

    def get_usage_today(self, user: str, day: date) -> int:
        row = self._conn.execute(
            "SELECT total_seconds FROM daily_usage WHERE user = ? AND date = ?",
            (user, day.isoformat()),
        ).fetchone()
        return row["total_seconds"] if row else 0

    def add_time_grant(
        self,
        user: str,
        granted_at: datetime,
        extra_seconds: int,
        reason: Optional[str],
    ):
        self._conn.execute(
            "INSERT INTO time_grants (user, granted_at, extra_seconds, reason) VALUES (?, ?, ?, ?)",
            (user, granted_at.isoformat(), extra_seconds, reason),
        )
        self._conn.commit()

    def get_pending_grants(self, user: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, extra_seconds, reason FROM time_grants WHERE user = ? AND processed = 0",
            (user,),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_grant_processed(self, grant_id: int):
        self._conn.execute(
            "UPDATE time_grants SET processed = 1 WHERE id = ?",
            (grant_id,),
        )
        self._conn.commit()

    def get_usage_last_30_days(self, user: str) -> list[dict]:
        rows = self._conn.execute(
            """SELECT date, total_seconds FROM daily_usage
               WHERE user = ? AND date >= date('now', '-29 days')
               ORDER BY date DESC""",
            (user,),
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self._conn.close()
