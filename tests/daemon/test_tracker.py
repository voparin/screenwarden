import pytest
from datetime import date, datetime
from unittest.mock import MagicMock, patch
from screenwarden.daemon.tracker import Tracker, TrackerState
from screenwarden.daemon.db import Database
from screenwarden.daemon.config import UserConfig


def make_db() -> Database:
    db = Database(":memory:")
    db.init_schema()
    return db


def make_config(limit_min=120, warn_min=5, grace_min=5) -> UserConfig:
    return UserConfig(
        daily_limit_minutes=limit_min,
        warning_minutes=warn_min,
        grace_minutes=grace_min,
    )


def test_initial_state_is_ok():
    tracker = Tracker("jakob", make_db(), make_config())
    assert tracker.state == TrackerState.OK


def test_tick_adds_seconds_when_session_active():
    db = make_db()
    tracker = Tracker("jakob", db, make_config())
    day = date(2026, 8, 27)
    tracker.tick(active=True, now=datetime(2026, 8, 27, 10, 0, 30), today=day)
    # 30 seconds added (tick interval)
    assert db.get_usage_today("jakob", day) == 30


def test_tick_does_not_add_seconds_when_inactive():
    db = make_db()
    tracker = Tracker("jakob", db, make_config())
    day = date(2026, 8, 27)
    tracker.tick(active=False, now=datetime(2026, 8, 27, 10, 0, 30), today=day)
    assert db.get_usage_today("jakob", day) == 0


def test_state_becomes_warning_at_threshold():
    db = make_db()
    config = make_config(limit_min=10, warn_min=5, grace_min=2)
    tracker = Tracker("jakob", db, config)
    day = date(2026, 8, 27)
    # Add 5 minutes (300s) = at warning threshold (10min - 5min)
    db.add_usage_seconds("jakob", day, 300)
    tracker.tick(active=True, now=datetime(2026, 8, 27, 10, 0, 30), today=day)
    assert tracker.state == TrackerState.WARNING


def test_state_becomes_grace_at_limit():
    db = make_db()
    config = make_config(limit_min=10, warn_min=5, grace_min=2)
    tracker = Tracker("jakob", db, config)
    day = date(2026, 8, 27)
    # Add 10 minutes (600s) = at limit
    db.add_usage_seconds("jakob", day, 600)
    tracker.tick(active=True, now=datetime(2026, 8, 27, 10, 0, 30), today=day)
    assert tracker.state == TrackerState.GRACE


def test_grant_extends_effective_limit():
    db = make_db()
    config = make_config(limit_min=10, warn_min=5, grace_min=2)
    tracker = Tracker("jakob", db, config)
    day = date(2026, 8, 27)
    db.add_usage_seconds("jakob", day, 600)  # at limit
    db.add_time_grant("jakob", datetime(2026, 8, 27, 10, 0, 0), 600, None)
    tracker.tick(active=True, now=datetime(2026, 8, 27, 10, 0, 30), today=day)
    # 10 min used + 10 min grant = 20 min effective limit, state should be OK
    assert tracker.state == TrackerState.OK


def test_grace_expires_transitions_to_locked():
    db = make_db()
    config = make_config(limit_min=1, warn_min=0, grace_min=1)
    tracker = Tracker("jakob", db, config)
    day = date(2026, 8, 27)
    db.add_usage_seconds("jakob", day, 60)  # at limit
    # First tick enters grace
    tracker.tick(active=True, now=datetime(2026, 8, 27, 10, 0, 0), today=day)
    assert tracker.state == TrackerState.GRACE
    # Add more seconds to exhaust grace
    db.add_usage_seconds("jakob", day, 60)
    tracker.tick(active=True, now=datetime(2026, 8, 27, 10, 1, 30), today=day)
    assert tracker.state == TrackerState.LOCKED
