import pytest
from datetime import date, datetime
from screenwarden.daemon.db import Database


@pytest.fixture
def db():
    d = Database(":memory:")
    d.init_schema()
    return d


def test_init_schema_creates_tables(db):
    conn = db._conn
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert tables == {"sessions", "daily_usage", "time_grants"}


def test_record_session_start(db):
    db.record_session_start("jakob", datetime(2026, 8, 27, 9, 0, 0))
    row = db._conn.execute("SELECT user FROM sessions").fetchone()
    assert row[0] == "jakob"


def test_record_session_end(db):
    db.record_session_start("jakob", datetime(2026, 8, 27, 9, 0, 0))
    session_id = db._conn.execute("SELECT id FROM sessions").fetchone()[0]
    db.record_session_end(session_id, datetime(2026, 8, 27, 9, 30, 0))
    row = db._conn.execute("SELECT duration_seconds FROM sessions").fetchone()
    assert row[0] == 1800


def test_add_usage_seconds_upserts(db):
    db.add_usage_seconds("jakob", date(2026, 8, 27), 300)
    db.add_usage_seconds("jakob", date(2026, 8, 27), 300)
    row = db._conn.execute("SELECT total_seconds FROM daily_usage").fetchone()
    assert row[0] == 600


def test_get_usage_today_returns_zero_if_no_row(db):
    assert db.get_usage_today("jakob", date(2026, 8, 27)) == 0


def test_get_usage_today_returns_accumulated(db):
    db.add_usage_seconds("jakob", date(2026, 8, 27), 500)
    assert db.get_usage_today("jakob", date(2026, 8, 27)) == 500


def test_add_time_grant(db):
    db.add_time_grant("jakob", datetime(2026, 8, 27, 15, 0, 0), 600, "homework done")
    row = db._conn.execute("SELECT extra_seconds, reason FROM time_grants").fetchone()
    assert (row["extra_seconds"], row["reason"]) == (600, "homework done")


def test_get_pending_grants_returns_unprocessed(db):
    db.add_time_grant("jakob", datetime(2026, 8, 27, 15, 0, 0), 600, None)
    grants = db.get_pending_grants("jakob")
    assert len(grants) == 1
    assert grants[0]["extra_seconds"] == 600


def test_mark_grant_processed(db):
    db.add_time_grant("jakob", datetime(2026, 8, 27, 15, 0, 0), 600, None)
    grant_id = db._conn.execute("SELECT id FROM time_grants").fetchone()[0]
    db.mark_grant_processed(grant_id)
    grants = db.get_pending_grants("jakob")
    assert grants == []


def test_get_usage_last_30_days(db):
    db.add_usage_seconds("jakob", date(2026, 8, 27), 3600)
    db.add_usage_seconds("jakob", date(2026, 8, 26), 1800)
    rows = db.get_usage_last_30_days("jakob", reference_date=date(2026, 8, 27))
    assert len(rows) == 2
    assert rows[0]["date"] == "2026-08-27"
    assert rows[0]["total_seconds"] == 3600
