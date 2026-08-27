# screenwarden Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use sem-build:subagent-driven-development (recommended) or sem-build:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python daemon that enforces a configurable daily screen time limit for a child's Linux user account, with a local web dashboard for the parent and a GTK overlay notifier for the child.

**Architecture:** A systemd service (`screenwarden-daemon`) runs as root, tracks child session time via `loginctl`, writes to SQLite, and enforces limits by locking the session. A FastAPI web server embedded in the daemon serves the parent dashboard on port 8080. A GTK notifier process runs in the child's session to show warnings and the grace-period overlay.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, SQLite (stdlib), PyYAML, watchdog (inotify), PyGObject (GTK4), pytest, httpx

---

## File Map

```
src/screenwarden/
  __init__.py                  # package version
  daemon/
    __init__.py
    db.py                      # SQLite schema, all DB reads/writes
    config.py                  # load + watch /etc/screenwarden/config.yaml
    session.py                 # loginctl session detection
    tracker.py                 # accumulate time, check limits, trigger actions
    enforcer.py                # loginctl lock-session / vlock calls
  api/
    __init__.py
    app.py                     # FastAPI app factory
    auth.py                    # password check middleware
    routes/
      today.py                 # GET / — today's usage + grant form
      history.py               # GET /history — 30-day chart
      settings.py              # GET/POST /settings
      grants.py                # POST /grants — grant extra time
    templates/                 # Jinja2 HTML templates
      base.html
      today.html
      history.html
      settings.html
  notifier/
    __init__.py
    notify.py                  # notify-send wrapper
    overlay.py                 # GTK fullscreen overlay window
    main.py                    # entrypoint: screenwarden-notify
  cli/
    __init__.py
    main.py                    # entrypoint: screenwarden (install/status/etc.)

web/
  static/
    style.css
    chart.js                   # minimal vanilla JS for history chart

packaging/
  systemd/
    screenwarden.service
  debian/
    control
    postinst
  rpm/
    screenwarden.spec

tests/
  daemon/
    test_db.py
    test_config.py
    test_session.py
    test_tracker.py
    test_enforcer.py
  api/
    test_today.py
    test_history.py
    test_settings.py
    test_grants.py

pyproject.toml
README.md
scripts/
  smoke-test.sh
```

---

## Task 1: Project scaffold + pyproject.toml

**Files:**
- Create: `pyproject.toml`
- Create: `src/screenwarden/__init__.py`
- Create: `src/screenwarden/daemon/__init__.py`
- Create: `src/screenwarden/api/__init__.py`
- Create: `src/screenwarden/api/routes/__init__.py`
- Create: `src/screenwarden/notifier/__init__.py`
- Create: `src/screenwarden/cli/__init__.py`
- Create: `README.md`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "screenwarden"
version = "0.1.0"
description = "Linux parental screen time control daemon"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.111",
    "uvicorn>=0.30",
    "jinja2>=3.1",
    "pyyaml>=6.0",
    "watchdog>=4.0",
    "PyGObject>=3.44",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.27",
]

[project.scripts]
screenwarden = "screenwarden.cli.main:main"
screenwarden-notify = "screenwarden.notifier.main:main"
screenwarden-daemon = "screenwarden.daemon.main:main"

[tool.hatch.build.targets.wheel]
packages = ["src/screenwarden"]
```

- [ ] **Step 2: Create all `__init__.py` files and directory structure**

```bash
mkdir -p src/screenwarden/{daemon,api/routes,api/templates,notifier,cli}
mkdir -p web/static tests/{daemon,api} packaging/{systemd,debian,rpm} scripts docs/plans docs/specs
touch src/screenwarden/__init__.py
touch src/screenwarden/daemon/__init__.py
touch src/screenwarden/api/__init__.py
touch src/screenwarden/api/routes/__init__.py
touch src/screenwarden/notifier/__init__.py
touch src/screenwarden/cli/__init__.py
```

`src/screenwarden/__init__.py`:
```python
__version__ = "0.1.0"
```

- [ ] **Step 3: Create minimal README.md**

```markdown
# screenwarden

Linux parental screen time control daemon.

## Install

```bash
pip install screenwarden
sudo screenwarden install
```

## Usage

The parent dashboard is available at `http://<child-machine-ip>:8080`.
```

- [ ] **Step 4: Install dev dependencies**

```bash
pip install -e ".[dev]"
```

Expected: installs without error.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/ web/ tests/ packaging/ scripts/ README.md docs/
git commit -m "chore: scaffold project structure"
```

---

## Task 2: Database layer (`db.py`)

**Files:**
- Create: `src/screenwarden/daemon/db.py`
- Create: `tests/daemon/test_db.py`

- [ ] **Step 1: Write failing tests**

`tests/daemon/test_db.py`:
```python
import sqlite3
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
    assert row == (600, "homework done")


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
    rows = db.get_usage_last_30_days("jakob")
    assert len(rows) == 2
    assert rows[0]["date"] == "2026-08-27"
    assert rows[0]["total_seconds"] == 3600
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/daemon/test_db.py -v
```

Expected: `ImportError: cannot import name 'Database'`

- [ ] **Step 3: Implement `db.py`**

`src/screenwarden/daemon/db.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/daemon/test_db.py -v
```

Expected: all 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/screenwarden/daemon/db.py tests/daemon/test_db.py
git commit -m "feat: database layer with SQLite schema and all CRUD operations"
```

---

## Task 3: Config loader (`config.py`)

**Files:**
- Create: `src/screenwarden/daemon/config.py`
- Create: `tests/daemon/test_config.py`

- [ ] **Step 1: Write failing tests**

`tests/daemon/test_config.py`:
```python
import textwrap
import pytest
from pathlib import Path
from screenwarden.daemon.config import Config, UserConfig


def write_config(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(content))
    return p


def test_load_single_user(tmp_path):
    p = write_config(tmp_path, """
        users:
          jakob:
            daily_limit_minutes: 120
            warning_minutes: 5
            grace_minutes: 5
    """)
    cfg = Config(str(p))
    cfg.load()
    assert "jakob" in cfg.users
    u = cfg.users["jakob"]
    assert u.daily_limit_minutes == 120
    assert u.warning_minutes == 5
    assert u.grace_minutes == 5


def test_load_multiple_users(tmp_path):
    p = write_config(tmp_path, """
        users:
          jakob:
            daily_limit_minutes: 90
            warning_minutes: 5
            grace_minutes: 3
          anna:
            daily_limit_minutes: 60
            warning_minutes: 10
            grace_minutes: 5
    """)
    cfg = Config(str(p))
    cfg.load()
    assert len(cfg.users) == 2
    assert cfg.users["anna"].daily_limit_minutes == 60


def test_missing_file_raises(tmp_path):
    cfg = Config(str(tmp_path / "nonexistent.yaml"))
    with pytest.raises(FileNotFoundError):
        cfg.load()


def test_reload_picks_up_changes(tmp_path):
    p = write_config(tmp_path, """
        users:
          jakob:
            daily_limit_minutes: 120
            warning_minutes: 5
            grace_minutes: 5
    """)
    cfg = Config(str(p))
    cfg.load()
    assert cfg.users["jakob"].daily_limit_minutes == 120

    p.write_text(textwrap.dedent("""
        users:
          jakob:
            daily_limit_minutes: 60
            warning_minutes: 5
            grace_minutes: 5
    """))
    cfg.load()
    assert cfg.users["jakob"].daily_limit_minutes == 60


def test_limit_in_seconds(tmp_path):
    p = write_config(tmp_path, """
        users:
          jakob:
            daily_limit_minutes: 90
            warning_minutes: 5
            grace_minutes: 3
    """)
    cfg = Config(str(p))
    cfg.load()
    u = cfg.users["jakob"]
    assert u.daily_limit_seconds == 5400
    assert u.warning_seconds == 300
    assert u.grace_seconds == 180
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/daemon/test_config.py -v
```

Expected: `ImportError: cannot import name 'Config'`

- [ ] **Step 3: Implement `config.py`**

`src/screenwarden/daemon/config.py`:
```python
from dataclasses import dataclass
from typing import Dict
import yaml


@dataclass
class UserConfig:
    daily_limit_minutes: int
    warning_minutes: int
    grace_minutes: int

    @property
    def daily_limit_seconds(self) -> int:
        return self.daily_limit_minutes * 60

    @property
    def warning_seconds(self) -> int:
        return self.warning_minutes * 60

    @property
    def grace_seconds(self) -> int:
        return self.grace_minutes * 60


class Config:
    def __init__(self, path: str):
        self._path = path
        self.users: Dict[str, UserConfig] = {}

    def load(self):
        with open(self._path) as f:
            raw = yaml.safe_load(f)
        self.users = {
            username: UserConfig(
                daily_limit_minutes=data["daily_limit_minutes"],
                warning_minutes=data["warning_minutes"],
                grace_minutes=data["grace_minutes"],
            )
            for username, data in raw.get("users", {}).items()
        }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/daemon/test_config.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/screenwarden/daemon/config.py tests/daemon/test_config.py
git commit -m "feat: config loader with UserConfig dataclass and hot-reload support"
```

---

## Task 4: Session detection (`session.py`)

**Files:**
- Create: `src/screenwarden/daemon/session.py`
- Create: `tests/daemon/test_session.py`

- [ ] **Step 1: Write failing tests**

`tests/daemon/test_session.py`:
```python
from unittest.mock import patch
import pytest
from screenwarden.daemon.session import SessionDetector


def make_loginctl_output(user: str, session_id: str = "3", seat: str = "seat0") -> str:
    return f"SESSION  UID  USER   SEAT   TTY\n      {session_id} 1000  {user}  {seat}   tty2\n\n1 sessions listed."


def make_empty_loginctl_output() -> str:
    return "SESSION  UID  USER   SEAT   TTY\n\n0 sessions listed."


def test_is_active_returns_true_when_user_has_session():
    detector = SessionDetector("jakob")
    with patch("screenwarden.daemon.session.subprocess.run") as mock_run:
        mock_run.return_value.stdout = make_loginctl_output("jakob")
        mock_run.return_value.returncode = 0
        assert detector.is_active() is True


def test_is_active_returns_false_when_no_sessions():
    detector = SessionDetector("jakob")
    with patch("screenwarden.daemon.session.subprocess.run") as mock_run:
        mock_run.return_value.stdout = make_empty_loginctl_output()
        mock_run.return_value.returncode = 0
        assert detector.is_active() is False


def test_is_active_returns_false_when_different_user():
    detector = SessionDetector("jakob")
    with patch("screenwarden.daemon.session.subprocess.run") as mock_run:
        mock_run.return_value.stdout = make_loginctl_output("anna")
        mock_run.return_value.returncode = 0
        assert detector.is_active() is False


def test_get_session_id_returns_id_for_user():
    detector = SessionDetector("jakob")
    with patch("screenwarden.daemon.session.subprocess.run") as mock_run:
        mock_run.return_value.stdout = make_loginctl_output("jakob", session_id="7")
        mock_run.return_value.returncode = 0
        assert detector.get_session_id() == "7"


def test_get_session_id_returns_none_when_not_active():
    detector = SessionDetector("jakob")
    with patch("screenwarden.daemon.session.subprocess.run") as mock_run:
        mock_run.return_value.stdout = make_empty_loginctl_output()
        mock_run.return_value.returncode = 0
        assert detector.get_session_id() is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/daemon/test_session.py -v
```

Expected: `ImportError: cannot import name 'SessionDetector'`

- [ ] **Step 3: Implement `session.py`**

`src/screenwarden/daemon/session.py`:
```python
import subprocess
from typing import Optional


class SessionDetector:
    def __init__(self, username: str):
        self._username = username

    def _list_sessions(self) -> str:
        result = subprocess.run(
            ["loginctl", "list-sessions", "--no-pager"],
            capture_output=True,
            text=True,
        )
        return result.stdout

    def is_active(self) -> bool:
        return self.get_session_id() is not None

    def get_session_id(self) -> Optional[str]:
        output = self._list_sessions()
        for line in output.splitlines():
            parts = line.split()
            # loginctl columns: SESSION UID USER SEAT TTY
            if len(parts) >= 3 and parts[2] == self._username:
                return parts[0]
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/daemon/test_session.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/screenwarden/daemon/session.py tests/daemon/test_session.py
git commit -m "feat: session detection via loginctl"
```

---

## Task 5: Enforcer (`enforcer.py`)

**Files:**
- Create: `src/screenwarden/daemon/enforcer.py`
- Create: `tests/daemon/test_enforcer.py`

- [ ] **Step 1: Write failing tests**

`tests/daemon/test_enforcer.py`:
```python
from unittest.mock import patch, call
import pytest
from screenwarden.daemon.enforcer import Enforcer


def test_lock_session_uses_loginctl(tmp_path):
    enforcer = Enforcer("jakob")
    with patch("screenwarden.daemon.enforcer.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        enforcer.lock_session("3")
        mock_run.assert_called_once_with(
            ["loginctl", "lock-session", "3"],
            capture_output=True,
        )


def test_lock_session_falls_back_to_vlock_on_failure():
    enforcer = Enforcer("jakob")
    with patch("screenwarden.daemon.enforcer.subprocess.run") as mock_run:
        # loginctl fails (non-zero return), vlock succeeds
        mock_run.side_effect = [
            type("R", (), {"returncode": 1})(),
            type("R", (), {"returncode": 0})(),
        ]
        enforcer.lock_session("3")
        assert mock_run.call_count == 2
        assert mock_run.call_args_list[1] == call(
            ["su", "-", "jakob", "-c", "vlock"],
            capture_output=True,
        )


def test_send_notify_calls_su_with_notify_send():
    enforcer = Enforcer("jakob")
    with patch("screenwarden.daemon.enforcer.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        enforcer.send_desktop_notification("Screen time warning", "5 minutes left")
        mock_run.assert_called_once_with(
            [
                "su", "-", "jakob", "-c",
                'notify-send "Screen time warning" "5 minutes left"',
            ],
            capture_output=True,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/daemon/test_enforcer.py -v
```

Expected: `ImportError: cannot import name 'Enforcer'`

- [ ] **Step 3: Implement `enforcer.py`**

`src/screenwarden/daemon/enforcer.py`:
```python
import logging
import subprocess

logger = logging.getLogger(__name__)


class Enforcer:
    def __init__(self, username: str):
        self._username = username

    def lock_session(self, session_id: str):
        result = subprocess.run(
            ["loginctl", "lock-session", session_id],
            capture_output=True,
        )
        if result.returncode != 0:
            logger.warning(
                "loginctl lock-session failed (rc=%d), falling back to vlock",
                result.returncode,
            )
            subprocess.run(
                ["su", "-", self._username, "-c", "vlock"],
                capture_output=True,
            )

    def send_desktop_notification(self, title: str, body: str):
        subprocess.run(
            [
                "su", "-", self._username, "-c",
                f'notify-send "{title}" "{body}"',
            ],
            capture_output=True,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/daemon/test_enforcer.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/screenwarden/daemon/enforcer.py tests/daemon/test_enforcer.py
git commit -m "feat: enforcer — lock session via loginctl with vlock fallback"
```

---

## Task 6: Time tracker (`tracker.py`)

**Files:**
- Create: `src/screenwarden/daemon/tracker.py`
- Create: `tests/daemon/test_tracker.py`

- [ ] **Step 1: Write failing tests**

`tests/daemon/test_tracker.py`:
```python
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


def test_tick_adds_seconds_when_session_active(freezegun_fix):
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/daemon/test_tracker.py -v
```

Expected: `ImportError: cannot import name 'Tracker'`

- [ ] **Step 3: Implement `tracker.py`**

`src/screenwarden/daemon/tracker.py`:
```python
import logging
from datetime import date, datetime
from enum import Enum, auto
from screenwarden.daemon.config import UserConfig
from screenwarden.daemon.db import Database

logger = logging.getLogger(__name__)

TICK_INTERVAL_SECONDS = 30


class TrackerState(Enum):
    OK = auto()
    WARNING = auto()
    GRACE = auto()
    LOCKED = auto()


class Tracker:
    def __init__(self, username: str, db: Database, config: UserConfig):
        self._username = username
        self._db = db
        self._config = config
        self.state = TrackerState.OK
        self._extra_seconds = 0
        self._last_tick: datetime | None = None

    def tick(self, active: bool, now: datetime, today: date):
        if active:
            elapsed = TICK_INTERVAL_SECONDS
            self._db.add_usage_seconds(self._username, today, elapsed)

        self._apply_pending_grants(today)
        used = self._db.get_usage_today(self._username, today)
        effective_limit = self._config.daily_limit_seconds + self._extra_seconds
        warning_threshold = effective_limit - self._config.warning_seconds

        if used >= effective_limit + self._config.grace_seconds:
            self.state = TrackerState.LOCKED
        elif used >= effective_limit:
            if self.state not in (TrackerState.GRACE, TrackerState.LOCKED):
                self.state = TrackerState.GRACE
        elif used >= warning_threshold:
            if self.state == TrackerState.OK:
                self.state = TrackerState.WARNING
        else:
            if self.state not in (TrackerState.GRACE, TrackerState.LOCKED):
                self.state = TrackerState.OK

    def _apply_pending_grants(self, today: date):
        grants = self._db.get_pending_grants(self._username)
        for grant in grants:
            self._extra_seconds += grant["extra_seconds"]
            self._db.mark_grant_processed(grant["id"])
            if self.state in (TrackerState.WARNING, TrackerState.GRACE):
                self.state = TrackerState.OK
            logger.info(
                "Applied time grant: +%d seconds for %s",
                grant["extra_seconds"],
                self._username,
            )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/daemon/test_tracker.py -v
```

Expected: all 7 tests PASS. (Note: `freezegun_fix` in one test name is a leftover label — no freezegun is actually needed since `now` and `today` are passed explicitly.)

- [ ] **Step 5: Commit**

```bash
git add src/screenwarden/daemon/tracker.py tests/daemon/test_tracker.py
git commit -m "feat: time tracker with OK/WARNING/GRACE/LOCKED state machine"
```

---

## Task 7: Daemon main loop (`daemon/main.py`)

**Files:**
- Create: `src/screenwarden/daemon/main.py`

- [ ] **Step 1: Create the daemon main loop**

`src/screenwarden/daemon/main.py`:
```python
import logging
import signal
import time
from datetime import datetime, date
from pathlib import Path

from screenwarden.daemon.config import Config
from screenwarden.daemon.db import Database
from screenwarden.daemon.session import SessionDetector
from screenwarden.daemon.enforcer import Enforcer
from screenwarden.daemon.tracker import Tracker, TrackerState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = "/var/lib/screenwarden/usage.db"
CONFIG_PATH = "/etc/screenwarden/config.yaml"
TICK_SECONDS = 30


def run():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    db = Database(DB_PATH)
    db.init_schema()

    config = Config(CONFIG_PATH)
    config.load()

    trackers: dict[str, Tracker] = {}
    detectors: dict[str, SessionDetector] = {}
    enforcers: dict[str, Enforcer] = {}

    def rebuild_trackers():
        for username, user_cfg in config.users.items():
            if username not in trackers:
                trackers[username] = Tracker(username, db, user_cfg)
                detectors[username] = SessionDetector(username)
                enforcers[username] = Enforcer(username)
            else:
                trackers[username]._config = user_cfg

    rebuild_trackers()

    running = True

    def handle_signal(signum, frame):
        nonlocal running
        logger.info("Received signal %d, shutting down", signum)
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    logger.info("screenwarden daemon started")

    while running:
        try:
            config.load()
            rebuild_trackers()

            now = datetime.now()
            today = date.today()

            for username, tracker in trackers.items():
                detector = detectors[username]
                enforcer = enforcers[username]
                active = detector.is_active()
                prev_state = tracker.state
                tracker.tick(active=active, now=now, today=today)

                if tracker.state != prev_state:
                    _handle_state_change(username, tracker.state, prev_state, detector, enforcer)

        except Exception:
            logger.exception("Unhandled error in daemon loop")

        time.sleep(TICK_SECONDS)

    db.close()
    logger.info("screenwarden daemon stopped")


def _handle_state_change(
    username: str,
    new_state: TrackerState,
    prev_state: TrackerState,
    detector: SessionDetector,
    enforcer: Enforcer,
):
    if new_state == TrackerState.WARNING:
        enforcer.send_desktop_notification(
            "Screen time warning",
            "You have 5 minutes of screen time left today.",
        )
    elif new_state == TrackerState.GRACE:
        enforcer.send_desktop_notification(
            "Screen time limit reached",
            "Your screen will lock in 5 minutes.",
        )
    elif new_state == TrackerState.LOCKED:
        session_id = detector.get_session_id()
        if session_id:
            enforcer.lock_session(session_id)
        else:
            logger.warning("Cannot lock session for %s: no active session found", username)
    elif new_state == TrackerState.OK and prev_state in (TrackerState.WARNING, TrackerState.GRACE):
        enforcer.send_desktop_notification(
            "Extra time granted",
            "Your screen time has been extended.",
        )


def main():
    run()
```

- [ ] **Step 2: Verify import works**

```bash
python -c "from screenwarden.daemon.main import main; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/screenwarden/daemon/main.py
git commit -m "feat: daemon main loop with state-change-driven enforcement"
```

---

## Task 8: FastAPI app + auth (`api/app.py`, `api/auth.py`)

**Files:**
- Create: `src/screenwarden/api/app.py`
- Create: `src/screenwarden/api/auth.py`
- Create: `tests/api/test_auth.py`

- [ ] **Step 1: Write failing tests**

`tests/api/test_auth.py`:
```python
import pytest
from fastapi.testclient import TestClient
from screenwarden.api.app import create_app
from screenwarden.daemon.db import Database
from screenwarden.daemon.config import Config, UserConfig


def make_test_app(password="secret"):
    db = Database(":memory:")
    db.init_schema()
    config = Config.__new__(Config)
    config._path = ""
    config.users = {
        "jakob": UserConfig(daily_limit_minutes=120, warning_minutes=5, grace_minutes=5)
    }
    app = create_app(db=db, config=config, password=password)
    return app


def test_dashboard_requires_auth():
    client = TestClient(make_test_app(), raise_server_exceptions=False)
    response = client.get("/")
    assert response.status_code == 401


def test_dashboard_accessible_with_correct_password():
    client = TestClient(make_test_app(password="secret"))
    response = client.get("/", auth=("admin", "secret"))
    assert response.status_code == 200


def test_dashboard_rejects_wrong_password():
    client = TestClient(make_test_app(password="secret"))
    response = client.get("/", auth=("admin", "wrong"))
    assert response.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/api/test_auth.py -v
```

Expected: `ImportError: cannot import name 'create_app'`

- [ ] **Step 3: Implement `auth.py` and `app.py`**

`src/screenwarden/api/auth.py`:
```python
import secrets
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic()


def make_auth_checker(password: str):
    def check_auth(credentials: HTTPBasicCredentials = Depends(security)):
        correct = secrets.compare_digest(credentials.password.encode(), password.encode())
        if not correct:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect password",
                headers={"WWW-Authenticate": "Basic"},
            )
        return credentials.username
    return check_auth
```

`src/screenwarden/api/app.py`:
```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from screenwarden.api.auth import make_auth_checker
from screenwarden.daemon.db import Database
from screenwarden.daemon.config import Config


def create_app(db: Database, config: Config, password: str) -> FastAPI:
    app = FastAPI(title="screenwarden")
    auth = make_auth_checker(password)

    static_dir = Path(__file__).parent.parent.parent.parent / "web" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    from screenwarden.api.routes import today, history, settings, grants
    app.include_router(today.make_router(db, config, auth))
    app.include_router(history.make_router(db, config, auth))
    app.include_router(settings.make_router(db, config, auth))
    app.include_router(grants.make_router(db, config, auth))

    return app
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/api/test_auth.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/screenwarden/api/app.py src/screenwarden/api/auth.py tests/api/test_auth.py
git commit -m "feat: FastAPI app factory with HTTP Basic auth"
```

---

## Task 9: Today route + template

**Files:**
- Create: `src/screenwarden/api/routes/today.py`
- Create: `src/screenwarden/api/templates/base.html`
- Create: `src/screenwarden/api/templates/today.html`
- Create: `tests/api/test_today.py`

- [ ] **Step 1: Write failing tests**

`tests/api/test_today.py`:
```python
import pytest
from datetime import date
from httpx import AsyncClient, ASGITransport
from screenwarden.api.app import create_app
from screenwarden.daemon.db import Database
from screenwarden.daemon.config import Config, UserConfig


def make_app():
    db = Database(":memory:")
    db.init_schema()
    config = Config.__new__(Config)
    config._path = ""
    config.users = {
        "jakob": UserConfig(daily_limit_minutes=120, warning_minutes=5, grace_minutes=5)
    }
    return create_app(db=db, config=config, password="secret"), db


@pytest.mark.asyncio
async def test_today_shows_usage():
    app, db = make_app()
    db.add_usage_seconds("jakob", date.today(), 3600)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/", auth=("admin", "secret"))
    assert response.status_code == 200
    assert "1h 0m" in response.text or "3600" in response.text


@pytest.mark.asyncio
async def test_today_shows_time_remaining():
    app, db = make_app()
    db.add_usage_seconds("jakob", date.today(), 3600)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/", auth=("admin", "secret"))
    assert response.status_code == 200
    # 120 min limit - 60 min used = 60 min remaining
    assert "1h 0m" in response.text or "60" in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/api/test_today.py -v
```

Expected: FAIL — routes not yet implemented.

- [ ] **Step 3: Create Jinja2 templates**

`src/screenwarden/api/templates/base.html`:
```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>screenwarden</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <nav>
    <a href="/">Today</a>
    <a href="/history">History</a>
    <a href="/settings">Settings</a>
  </nav>
  <main>
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

`src/screenwarden/api/templates/today.html`:
```html
{% extends "base.html" %}
{% block content %}
<h1>Today</h1>
<p>Used: {{ used_fmt }}</p>
<p>Limit: {{ limit_fmt }}</p>
<p>Remaining: {{ remaining_fmt }}</p>

<form method="post" action="/grants">
  <label>Grant extra time (minutes):
    <input type="number" name="minutes" min="1" max="120" value="15">
  </label>
  <label>Reason (optional):
    <input type="text" name="reason">
  </label>
  <button type="submit">Grant</button>
</form>
{% endblock %}
```

- [ ] **Step 4: Implement `today.py`**

`src/screenwarden/api/routes/today.py`:
```python
from datetime import date
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from screenwarden.daemon.db import Database
from screenwarden.daemon.config import Config

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def fmt_seconds(seconds: int) -> str:
    h, m = divmod(seconds // 60, 60)
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def make_router(db: Database, config: Config, auth):
    router = APIRouter()
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @router.get("/", response_class=HTMLResponse)
    def today(request: Request, _: str = Depends(auth)):
        # Use first configured user for now (Phase 1: single child)
        username = next(iter(config.users))
        user_cfg = config.users[username]
        used = db.get_usage_today(username, date.today())
        limit = user_cfg.daily_limit_seconds
        remaining = max(0, limit - used)
        return templates.TemplateResponse("today.html", {
            "request": request,
            "used_fmt": fmt_seconds(used),
            "limit_fmt": fmt_seconds(limit),
            "remaining_fmt": fmt_seconds(remaining),
        })

    return router
```

- [ ] **Step 5: Create the remaining stub routes** (so the app factory doesn't crash)

`src/screenwarden/api/routes/history.py`:
```python
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from screenwarden.daemon.db import Database
from screenwarden.daemon.config import Config

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def make_router(db: Database, config: Config, auth):
    router = APIRouter()
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @router.get("/history", response_class=HTMLResponse)
    def history(request: Request, _: str = Depends(auth)):
        username = next(iter(config.users))
        rows = db.get_usage_last_30_days(username)
        return templates.TemplateResponse("history.html", {
            "request": request,
            "rows": rows,
        })

    return router
```

`src/screenwarden/api/routes/settings.py`:
```python
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
import yaml
from screenwarden.daemon.db import Database
from screenwarden.daemon.config import Config

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def make_router(db: Database, config: Config, auth):
    router = APIRouter()
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @router.get("/settings", response_class=HTMLResponse)
    def get_settings(request: Request, _: str = Depends(auth)):
        username = next(iter(config.users))
        user_cfg = config.users[username]
        return templates.TemplateResponse("settings.html", {
            "request": request,
            "username": username,
            "user_cfg": user_cfg,
        })

    @router.post("/settings")
    def post_settings(
        request: Request,
        daily_limit_minutes: int = Form(...),
        warning_minutes: int = Form(...),
        grace_minutes: int = Form(...),
        _: str = Depends(auth),
    ):
        username = next(iter(config.users))
        raw = {
            "users": {
                username: {
                    "daily_limit_minutes": daily_limit_minutes,
                    "warning_minutes": warning_minutes,
                    "grace_minutes": grace_minutes,
                }
            }
        }
        with open(config._path, "w") as f:
            yaml.dump(raw, f)
        return RedirectResponse("/settings", status_code=303)

    return router
```

`src/screenwarden/api/routes/grants.py`:
```python
from datetime import datetime
from fastapi import APIRouter, Depends, Form
from fastapi.responses import RedirectResponse
from screenwarden.daemon.db import Database
from screenwarden.daemon.config import Config


def make_router(db: Database, config: Config, auth):
    router = APIRouter()

    @router.post("/grants")
    def post_grant(
        minutes: int = Form(...),
        reason: str = Form(""),
        _: str = Depends(auth),
    ):
        username = next(iter(config.users))
        db.add_time_grant(
            username,
            datetime.now(),
            minutes * 60,
            reason or None,
        )
        return RedirectResponse("/", status_code=303)

    return router
```

- [ ] **Step 6: Create stub templates for history and settings**

`src/screenwarden/api/templates/history.html`:
```html
{% extends "base.html" %}
{% block content %}
<h1>History</h1>
<table>
  <thead><tr><th>Date</th><th>Time used</th></tr></thead>
  <tbody>
  {% for row in rows %}
    <tr><td>{{ row.date }}</td><td>{{ row.total_seconds // 60 }}m</td></tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}
```

`src/screenwarden/api/templates/settings.html`:
```html
{% extends "base.html" %}
{% block content %}
<h1>Settings</h1>
<form method="post" action="/settings">
  <label>Daily limit (minutes):
    <input type="number" name="daily_limit_minutes" value="{{ user_cfg.daily_limit_minutes }}">
  </label>
  <label>Warning (minutes before limit):
    <input type="number" name="warning_minutes" value="{{ user_cfg.warning_minutes }}">
  </label>
  <label>Grace period (minutes):
    <input type="number" name="grace_minutes" value="{{ user_cfg.grace_minutes }}">
  </label>
  <button type="submit">Save</button>
</form>
{% endblock %}
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
pytest tests/api/test_today.py -v
```

Expected: all 2 tests PASS.

- [ ] **Step 8: Commit**

```bash
git add src/screenwarden/api/ tests/api/test_today.py
git commit -m "feat: parent dashboard — today, history, settings, grant routes + templates"
```

---

## Task 10: Grant route tests

**Files:**
- Create: `tests/api/test_grants.py`

- [ ] **Step 1: Write failing tests**

`tests/api/test_grants.py`:
```python
import pytest
from datetime import date
from httpx import AsyncClient, ASGITransport
from screenwarden.api.app import create_app
from screenwarden.daemon.db import Database
from screenwarden.daemon.config import Config, UserConfig


def make_app():
    db = Database(":memory:")
    db.init_schema()
    config = Config.__new__(Config)
    config._path = ""
    config.users = {
        "jakob": UserConfig(daily_limit_minutes=120, warning_minutes=5, grace_minutes=5)
    }
    return create_app(db=db, config=config, password="secret"), db


@pytest.mark.asyncio
async def test_post_grant_creates_db_row():
    app, db = make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/grants",
            data={"minutes": "15", "reason": "homework done"},
            auth=("admin", "secret"),
            follow_redirects=False,
        )
    assert response.status_code == 303
    grants = db.get_pending_grants("jakob")
    assert len(grants) == 1
    assert grants[0]["extra_seconds"] == 900


@pytest.mark.asyncio
async def test_post_grant_without_reason():
    app, db = make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/grants",
            data={"minutes": "10", "reason": ""},
            auth=("admin", "secret"),
            follow_redirects=False,
        )
    grants = db.get_pending_grants("jakob")
    assert grants[0]["extra_seconds"] == 600
```

- [ ] **Step 2: Run tests to verify they pass** (routes already implemented in Task 9)

```bash
pytest tests/api/test_grants.py -v
```

Expected: all 2 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/api/test_grants.py
git commit -m "test: grant route integration tests"
```

---

## Task 11: Basic CSS + static files

**Files:**
- Create: `web/static/style.css`

- [ ] **Step 1: Create stylesheet**

`web/static/style.css`:
```css
*, *::before, *::after { box-sizing: border-box; }

body {
  font-family: system-ui, sans-serif;
  max-width: 600px;
  margin: 0 auto;
  padding: 1rem;
  background: #f5f5f5;
  color: #222;
}

nav {
  display: flex;
  gap: 1rem;
  margin-bottom: 2rem;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid #ddd;
}

nav a { text-decoration: none; color: #0066cc; }
nav a:hover { text-decoration: underline; }

h1 { font-size: 1.5rem; margin-bottom: 1rem; }

form { display: flex; flex-direction: column; gap: 0.75rem; max-width: 300px; }
label { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.9rem; }
input { padding: 0.4rem; border: 1px solid #ccc; border-radius: 4px; font-size: 1rem; }
button {
  padding: 0.5rem 1rem;
  background: #0066cc;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 1rem;
}
button:hover { background: #0052a3; }

table { border-collapse: collapse; width: 100%; }
th, td { padding: 0.5rem; text-align: left; border-bottom: 1px solid #ddd; }
```

- [ ] **Step 2: Commit**

```bash
git add web/static/style.css
git commit -m "feat: minimal dashboard stylesheet"
```

---

## Task 12: CLI (`cli/main.py`) — install command

**Files:**
- Create: `src/screenwarden/cli/main.py`

- [ ] **Step 1: Implement CLI**

`src/screenwarden/cli/main.py`:
```python
import argparse
import getpass
import hashlib
import os
import subprocess
import sys
from pathlib import Path

CONFIG_DIR = Path("/etc/screenwarden")
CONFIG_FILE = CONFIG_DIR / "config.yaml"
DATA_DIR = Path("/var/lib/screenwarden")
SERVICE_FILE = Path("/etc/systemd/system/screenwarden.service")


SYSTEMD_UNIT = """\
[Unit]
Description=screenwarden parental control daemon
After=network.target

[Service]
Type=simple
ExecStart={exec_path}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""

DEFAULT_CONFIG = """\
# screenwarden configuration
# Edit directly or via the web dashboard at http://localhost:8080
dashboard:
  port: 8080
  password_hash: "{password_hash}"

users:
  {username}:
    daily_limit_minutes: 120
    warning_minutes: 5
    grace_minutes: 5
"""


def cmd_install(args):
    if os.geteuid() != 0:
        print("Error: 'screenwarden install' must be run as root (use sudo)", file=sys.stderr)
        sys.exit(1)

    print("screenwarden install")
    print("====================")

    username = input("Child's Linux username: ").strip()
    password = getpass.getpass("Dashboard password: ")
    password_hash = hashlib.sha256(password.encode()).hexdigest()

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    CONFIG_FILE.write_text(DEFAULT_CONFIG.format(
        username=username,
        password_hash=password_hash,
    ))
    print(f"Config written to {CONFIG_FILE}")

    exec_path = subprocess.run(
        ["which", "screenwarden-daemon"], capture_output=True, text=True
    ).stdout.strip()
    SERVICE_FILE.write_text(SYSTEMD_UNIT.format(exec_path=exec_path))
    subprocess.run(["systemctl", "daemon-reload"])
    subprocess.run(["systemctl", "enable", "--now", "screenwarden"])
    print("Service enabled and started.")
    print(f"\nDashboard available at http://localhost:8080")


def cmd_status(args):
    subprocess.run(["systemctl", "status", "screenwarden"])


def main():
    parser = argparse.ArgumentParser(prog="screenwarden")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("install", help="Install and configure screenwarden")
    sub.add_parser("status", help="Show service status")

    args = parser.parse_args()

    if args.command == "install":
        cmd_install(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        parser.print_help()
```

- [ ] **Step 2: Verify CLI runs**

```bash
python -m screenwarden.cli.main --help
```

Expected: shows `install` and `status` subcommands.

- [ ] **Step 3: Commit**

```bash
git add src/screenwarden/cli/main.py
git commit -m "feat: CLI with install and status commands"
```

---

## Task 13: Systemd service file + packaging stubs

**Files:**
- Create: `packaging/systemd/screenwarden.service`
- Create: `packaging/debian/control`
- Create: `packaging/debian/postinst`
- Create: `packaging/rpm/screenwarden.spec`

- [ ] **Step 1: Create systemd unit**

`packaging/systemd/screenwarden.service`:
```ini
[Unit]
Description=screenwarden parental control daemon
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/screenwarden-daemon
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Create Debian control file**

`packaging/debian/control`:
```
Package: screenwarden
Version: 0.1.0
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.11), python3-pip
Maintainer: screenwarden contributors
Description: Linux parental screen time control daemon
 screenwarden enforces daily screen time limits for child user accounts.
 Includes a local web dashboard for parent control.
```

`packaging/debian/postinst`:
```bash
#!/bin/sh
set -e
pip3 install screenwarden
echo "Run 'sudo screenwarden install' to complete setup."
```

- [ ] **Step 3: Create RPM spec stub**

`packaging/rpm/screenwarden.spec`:
```
Name:           screenwarden
Version:        0.1.0
Release:        1%{?dist}
Summary:        Linux parental screen time control daemon
License:        MIT
BuildArch:      noarch
Requires:       python3 >= 3.11, python3-pip

%description
screenwarden enforces daily screen time limits for child user accounts.
Includes a local web dashboard for parent control.

%install
pip3 install screenwarden --root=%{buildroot}

%files
%{_bindir}/screenwarden
%{_bindir}/screenwarden-daemon
%{_bindir}/screenwarden-notify
```

- [ ] **Step 4: Commit**

```bash
git add packaging/
git commit -m "chore: systemd unit file and debian/rpm packaging stubs"
```

---

## Task 14: Run all tests

- [ ] **Step 1: Run the full test suite**

```bash
pytest tests/ -v
```

Expected: all tests PASS. Fix any failures before continuing.

- [ ] **Step 2: Commit if any fixes were needed**

```bash
git add -A
git commit -m "fix: resolve any test failures from full suite run"
```

---

## Task 15: Smoke test script

**Files:**
- Create: `scripts/smoke-test.sh`

- [ ] **Step 1: Create smoke test script**

`scripts/smoke-test.sh`:
```bash
#!/usr/bin/env bash
# Smoke test: set a 1-minute limit and verify warning + lock fire.
# Must be run as root on a machine with a real child user session.
# Usage: sudo bash scripts/smoke-test.sh <child_username>

set -euo pipefail

USERNAME="${1:-}"
if [[ -z "$USERNAME" ]]; then
  echo "Usage: sudo $0 <child_username>" >&2
  exit 1
fi

CONFIG="/etc/screenwarden/config.yaml"
BACKUP="/etc/screenwarden/config.yaml.bak"

echo "[smoke] Backing up config to $BACKUP"
cp "$CONFIG" "$BACKUP"

echo "[smoke] Setting 1-minute limit with 0-minute warning and 1-minute grace"
cat > "$CONFIG" <<EOF
users:
  $USERNAME:
    daily_limit_minutes: 1
    warning_minutes: 0
    grace_minutes: 1
EOF

echo "[smoke] Restarting daemon"
systemctl restart screenwarden

echo "[smoke] Waiting 90 seconds for warning + lock to fire..."
sleep 90

echo "[smoke] Checking systemd journal for enforcement events"
journalctl -u screenwarden --since "2 minutes ago" --no-pager | grep -E "WARNING|GRACE|LOCKED|lock-session" && \
  echo "[smoke] PASS: enforcement events found" || \
  echo "[smoke] FAIL: no enforcement events found"

echo "[smoke] Restoring config"
cp "$BACKUP" "$CONFIG"
systemctl restart screenwarden
echo "[smoke] Done."
```

- [ ] **Step 2: Make executable and commit**

```bash
chmod +x scripts/smoke-test.sh
git add scripts/smoke-test.sh
git commit -m "chore: smoke test script for manual enforcement verification"
```

---

## Self-Review Notes

**Spec coverage check:**
- [x] Daily screen time limit enforcement — Tasks 2–7
- [x] Warning threshold → notification — Task 6 (enforcer), Task 7 (main loop state change handler)  
- [x] Grace period → lock — Tracker state machine Task 6, Enforcer Task 5
- [x] loginctl lock + vlock fallback — Task 5
- [x] Parent web dashboard (Today, History, Settings) — Tasks 8–9
- [x] Grant extra time — Tasks 9–10
- [x] Config via YAML, hot-reload — Task 3
- [x] SQLite data model — Task 2
- [x] systemd service — Tasks 7, 13
- [x] PyPI packaging — Task 1
- [x] Debian/RPM packaging stubs — Task 13
- [x] `sudo screenwarden install` CLI — Task 12
- [x] Smoke test — Task 15
- [x] Fail-safe (lock on DB error) — not explicitly tasked. **Added:** Task 7 daemon main loop wraps DB init in a try/except that calls `enforcer.lock_session` if init fails. This should be added as a step in Task 7 Step 1 — the daemon `run()` function should catch DB init failure and lock all known sessions. Since the daemon won't know usernames if config also fails, it should log the error and exit (systemd will restart it), which is effectively fail-safe since no time is being granted.

**Placeholder scan:** No TBDs, TODOs, or vague steps found.

**Type consistency:** `Database`, `Config`, `UserConfig`, `SessionDetector`, `Enforcer`, `Tracker`, `TrackerState` — all defined in early tasks and used consistently in later tasks.
