# Daemon Cloud Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use sem-build:subagent-driven-development (recommended) or sem-build:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the screenwarden daemon to sync usage data to the cloud backend every 30 seconds and pick up commands (grants, config changes) issued by parents.

**Architecture:** Three focused changes — (1) `config.py` gains a `CloudConfig` dataclass parsed from the `cloud:` YAML section, (2) a new `cloud_sync.py` module encapsulates all HTTP communication with the cloud API using only stdlib, (3) `main.py` initialises `CloudSync` and calls it in the tick loop, and `cli/main.py` gains a `register` subcommand. All cloud errors are swallowed — local enforcement never depends on cloud reachability.

**Tech Stack:** Python 3.11, urllib.request (stdlib), existing pytest suite

---

## File Map

```
src/screenwarden/
  daemon/
    config.py         — add CloudConfig + parse cloud: section in Config.load()
    cloud_sync.py     — NEW: SyncResult dataclass + CloudSync class
    main.py           — init CloudSync after config.load(), add sync step in tick loop
  cli/
    main.py           — add register subcommand, add cloud: block to DEFAULT_CONFIG

tests/daemon/
  test_config.py      — add 2 tests for CloudConfig parsing
  test_cloud_sync.py  — NEW: 6 unit tests
```

---

## Task 1: Add `CloudConfig` to config.py

**Files:**
- Modify: `src/screenwarden/daemon/config.py`
- Modify: `tests/daemon/test_config.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/daemon/test_config.py`:

```python
def test_cloud_config_defaults_when_section_absent(tmp_path):
    p = write_config(tmp_path, """
        users:
          jakob:
            daily_limit_minutes: 120
            warning_minutes: 5
            grace_minutes: 5
    """)
    cfg = Config(str(p))
    cfg.load()
    assert cfg.cloud.api_url == "https://screenwarden-cloud.onrender.com"
    assert cfg.cloud.device_token == ""


def test_cloud_config_parsed_when_present(tmp_path):
    p = write_config(tmp_path, """
        users:
          jakob:
            daily_limit_minutes: 120
            warning_minutes: 5
            grace_minutes: 5
        cloud:
          api_url: https://custom.example.com
          device_token: abc123token
    """)
    cfg = Config(str(p))
    cfg.load()
    assert cfg.cloud.api_url == "https://custom.example.com"
    assert cfg.cloud.device_token == "abc123token"
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest tests/daemon/test_config.py -v -k "cloud"
```

Expected: `AttributeError: 'Config' object has no attribute 'cloud'`

- [ ] **Step 3: Update `src/screenwarden/daemon/config.py`**

Replace the entire file with:

```python
from dataclasses import dataclass
from typing import Dict
import yaml


@dataclass
class DashboardConfig:
    port: int = 8080
    password_hash: str = ""


@dataclass
class CloudConfig:
    api_url: str = "https://screenwarden-cloud.onrender.com"
    device_token: str = ""


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
        self.dashboard: DashboardConfig = DashboardConfig()
        self.cloud: CloudConfig = CloudConfig()

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
        dash = raw.get("dashboard", {})
        self.dashboard = DashboardConfig(
            port=dash.get("port", 8080),
            password_hash=dash.get("password_hash", ""),
        )
        cloud = raw.get("cloud", {})
        self.cloud = CloudConfig(
            api_url=cloud.get("api_url", "https://screenwarden-cloud.onrender.com"),
            device_token=cloud.get("device_token", ""),
        )
```

- [ ] **Step 4: Run all config tests to verify they pass**

```bash
.venv/bin/pytest tests/daemon/test_config.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/screenwarden/daemon/config.py tests/daemon/test_config.py
git commit -m "feat: add CloudConfig dataclass and parse cloud: section from config.yaml"
```

---

## Task 2: CloudSync module

**Files:**
- Create: `src/screenwarden/daemon/cloud_sync.py`
- Create: `tests/daemon/test_cloud_sync.py`

- [ ] **Step 1: Write failing tests**

`tests/daemon/test_cloud_sync.py`:

```python
import json
import pytest
from datetime import date
from unittest.mock import patch, MagicMock
from urllib.error import URLError
from screenwarden.daemon.cloud_sync import CloudSync, SyncResult


API_URL = "https://screenwarden-cloud.onrender.com"
TOKEN = "abc123devicetoken"


def make_response(body: dict, status: int = 200):
    mock = MagicMock()
    mock.status = status
    mock.read.return_value = json.dumps(body).encode()
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    return mock


def test_sync_sends_correct_payload():
    cs = CloudSync(API_URL, TOKEN)
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["method"] = req.method
        captured["token"] = req.get_header("X-device-token")
        body = json.loads(req.data.decode())
        captured["body"] = body
        return make_response({"commands": [], "config": {}})

    with patch("screenwarden.daemon.cloud_sync.urllib.request.urlopen", fake_urlopen):
        cs.sync(users={"jakob": 3600}, today=date(2026, 8, 29))

    assert captured["url"] == f"{API_URL}/sync"
    assert captured["method"] == "POST"
    assert captured["token"] == TOKEN
    assert len(captured["body"]["users"]) == 1
    assert captured["body"]["users"][0]["username"] == "jakob"
    assert captured["body"]["users"][0]["total_seconds"] == 3600
    assert captured["body"]["users"][0]["date"] == "2026-08-29"


def test_sync_returns_commands_and_config():
    cs = CloudSync(API_URL, TOKEN)
    response_body = {
        "commands": [
            {"id": "cmd-1", "username": "jakob", "type": "grant", "payload": {"extra_seconds": 900}}
        ],
        "config": {
            "jakob": {"daily_limit_minutes": 90, "warning_minutes": 5, "grace_minutes": 3}
        },
    }
    with patch("screenwarden.daemon.cloud_sync.urllib.request.urlopen",
               return_value=make_response(response_body)):
        result = cs.sync(users={"jakob": 0}, today=date(2026, 8, 29))

    assert len(result.commands) == 1
    assert result.commands[0]["type"] == "grant"
    assert result.config["jakob"]["daily_limit_minutes"] == 90


def test_sync_returns_empty_on_network_error():
    cs = CloudSync(API_URL, TOKEN)
    with patch("screenwarden.daemon.cloud_sync.urllib.request.urlopen",
               side_effect=URLError("connection refused")):
        result = cs.sync(users={"jakob": 0}, today=date(2026, 8, 29))

    assert result.commands == []
    assert result.config == {}


def test_sync_returns_empty_on_non_200():
    cs = CloudSync(API_URL, TOKEN)
    with patch("screenwarden.daemon.cloud_sync.urllib.request.urlopen",
               return_value=make_response({}, status=401)):
        result = cs.sync(users={"jakob": 0}, today=date(2026, 8, 29))

    assert result.commands == []
    assert result.config == {}


def test_register_returns_device_token():
    cs = CloudSync(API_URL, TOKEN)
    with patch("screenwarden.daemon.cloud_sync.urllib.request.urlopen",
               return_value=make_response({"device_token": "newtoken123"})):
        token = cs.register("SW-ABC123", "jakob-laptop")

    assert token == "newtoken123"


def test_register_raises_on_404():
    cs = CloudSync(API_URL, TOKEN)
    from urllib.error import HTTPError
    with patch("screenwarden.daemon.cloud_sync.urllib.request.urlopen",
               side_effect=HTTPError(None, 404, "Not Found", {}, None)):
        with pytest.raises(RuntimeError, match="not found or expired"):
            cs.register("SW-BADCODE", "jakob-laptop")
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest tests/daemon/test_cloud_sync.py -v
```

Expected: `ImportError: cannot import name 'CloudSync'`

- [ ] **Step 3: Create `src/screenwarden/daemon/cloud_sync.py`**

```python
import json
import logging
import socket
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from urllib.error import HTTPError, URLError

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    commands: list = field(default_factory=list)
    config: dict = field(default_factory=dict)


class CloudSync:
    def __init__(self, api_url: str, device_token: str):
        self._api_url = api_url.rstrip("/")
        self._device_token = device_token

    def sync(self, users: dict[str, int], today: date) -> SyncResult:
        payload = {
            "users": [
                {
                    "username": username,
                    "date": today.isoformat(),
                    "total_seconds": total_seconds,
                    "last_sync_at": datetime.now(timezone.utc).isoformat(),
                }
                for username, total_seconds in users.items()
            ]
        }
        try:
            req = urllib.request.Request(
                f"{self._api_url}/sync",
                data=json.dumps(payload).encode(),
                headers={
                    "Content-Type": "application/json",
                    "X-Device-Token": self._device_token,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status != 200:
                    logger.warning("Cloud sync returned status %d", resp.status)
                    return SyncResult()
                body = json.loads(resp.read().decode())
                return SyncResult(
                    commands=body.get("commands", []),
                    config=body.get("config", {}),
                )
        except (URLError, OSError, TimeoutError) as e:
            logger.warning("Cloud sync failed (network): %s", e)
            return SyncResult()
        except Exception as e:
            logger.warning("Cloud sync failed (unexpected): %s", e)
            return SyncResult()

    def register(self, pairing_code: str, device_name: str) -> str:
        payload = {"pairing_code": pairing_code, "device_name": device_name}
        try:
            req = urllib.request.Request(
                f"{self._api_url}/devices/register",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read().decode())
                return body["device_token"]
        except HTTPError as e:
            if e.code == 404:
                raise RuntimeError(
                    f"Pairing code '{pairing_code}' not found or expired. "
                    "Generate a new code in the screenwarden web app."
                ) from e
            raise RuntimeError(f"Registration failed: HTTP {e.code}") from e
        except URLError as e:
            raise RuntimeError(f"Cannot reach cloud API at {self._api_url}: {e}") from e
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/daemon/test_cloud_sync.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Run full suite to check for regressions**

```bash
.venv/bin/pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/screenwarden/daemon/cloud_sync.py tests/daemon/test_cloud_sync.py
git commit -m "feat: CloudSync module — sync usage, deliver commands, register device"
```

---

## Task 3: Wire CloudSync into daemon main loop

**Files:**
- Modify: `src/screenwarden/daemon/main.py`

- [ ] **Step 1: Read current `src/screenwarden/daemon/main.py`** (already done in context)

- [ ] **Step 2: Replace `src/screenwarden/daemon/main.py` with updated version**

```python
import logging
import signal
import threading
import time
from datetime import datetime, date
from pathlib import Path

import uvicorn

from screenwarden.api.app import create_app
from screenwarden.daemon.cloud_sync import CloudSync
from screenwarden.daemon.config import Config, UserConfig
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
    try:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        db = Database(DB_PATH)
        db.init_schema()
    except Exception:
        logger.exception("Failed to initialize database — failing safe (no time granted)")
        raise SystemExit(1)

    config = Config(CONFIG_PATH)
    config.load()

    # Start the parent dashboard API in a background thread
    api_app = create_app(db=db, config=config, password=config.dashboard.password_hash)
    api_thread = threading.Thread(
        target=uvicorn.run,
        args=(api_app,),
        kwargs={"host": "0.0.0.0", "port": config.dashboard.port, "log_level": "warning"},
        daemon=True,
    )
    api_thread.start()
    logger.info("Dashboard started on port %d", config.dashboard.port)

    cloud: CloudSync | None = (
        CloudSync(config.cloud.api_url, config.cloud.device_token)
        if config.cloud.device_token
        else None
    )
    if cloud:
        logger.info("Cloud sync enabled — %s", config.cloud.api_url)
    else:
        logger.info("Cloud sync disabled — no device_token configured")

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

            # Cloud sync — runs after local enforcement, never disrupts it
            if cloud:
                try:
                    result = cloud.sync(
                        users={u: db.get_usage_today(u, today) for u in trackers},
                        today=today,
                    )
                    for cmd in result.commands:
                        if cmd["type"] == "grant" and cmd["username"] in trackers:
                            db.add_time_grant(
                                cmd["username"],
                                datetime.now(),
                                cmd["payload"]["extra_seconds"],
                                None,
                            )
                            logger.info(
                                "Cloud grant applied: +%ds for %s",
                                cmd["payload"]["extra_seconds"],
                                cmd["username"],
                            )
                        elif cmd["type"] == "config_change" and cmd["username"] in config.users:
                            payload = cmd["payload"]
                            new_cfg = UserConfig(
                                daily_limit_minutes=payload["daily_limit_minutes"],
                                warning_minutes=payload["warning_minutes"],
                                grace_minutes=payload["grace_minutes"],
                            )
                            config.users[cmd["username"]] = new_cfg
                            trackers[cmd["username"]]._config = new_cfg
                            logger.info("Cloud config update applied for %s", cmd["username"])
                    for username, cfg in result.config.items():
                        if username in config.users:
                            new_cfg = UserConfig(**cfg)
                            if new_cfg != config.users[username]:
                                config.users[username] = new_cfg
                                trackers[username]._config = new_cfg
                except Exception:
                    logger.exception("Unexpected error in cloud sync — continuing with local config")

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

- [ ] **Step 3: Verify import works**

```bash
.venv/bin/python -c "from screenwarden.daemon.main import main; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Run full test suite**

```bash
.venv/bin/pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/screenwarden/daemon/main.py
git commit -m "feat: wire CloudSync into daemon tick loop — usage mirror + command delivery"
```

---

## Task 4: CLI register command + DEFAULT_CONFIG update

**Files:**
- Modify: `src/screenwarden/cli/main.py`

- [ ] **Step 1: Replace `src/screenwarden/cli/main.py` with updated version**

```python
import argparse
import getpass
import hashlib
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import yaml

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

cloud:
  api_url: https://screenwarden-cloud.onrender.com
  device_token: ""

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
    CONFIG_FILE.chmod(0o600)
    print(f"Config written to {CONFIG_FILE}")

    exec_path = shutil.which("screenwarden-daemon") or "/usr/bin/screenwarden-daemon"
    SERVICE_FILE.write_text(SYSTEMD_UNIT.format(exec_path=exec_path))
    subprocess.run(["systemctl", "daemon-reload"])
    subprocess.run(["systemctl", "enable", "--now", "screenwarden"])
    print("Service enabled and started.")
    print(f"\nDashboard available at http://localhost:8080")
    print(f"\nTo connect to the screenwarden cloud app, run:")
    print(f"  sudo screenwarden register <CODE>")
    print(f"(Get the code from https://screenwarden-cloud.onrender.com)")


def cmd_status(args):
    subprocess.run(["systemctl", "status", "screenwarden"])


def cmd_register(args):
    if os.geteuid() != 0:
        print("Error: 'screenwarden register' must be run as root (use sudo)", file=sys.stderr)
        sys.exit(1)

    if not CONFIG_FILE.exists():
        print(f"Error: config not found at {CONFIG_FILE}. Run 'sudo screenwarden install' first.",
              file=sys.stderr)
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        raw = yaml.safe_load(f)

    api_url = raw.get("cloud", {}).get("api_url", "https://screenwarden-cloud.onrender.com")
    device_name = socket.gethostname()

    from screenwarden.daemon.cloud_sync import CloudSync
    cloud = CloudSync(api_url, "")

    print(f"Registering device '{device_name}' with {api_url} ...")
    try:
        device_token = cloud.register(args.code, device_name)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Write device_token back to config
    if "cloud" not in raw:
        raw["cloud"] = {}
    raw["cloud"]["api_url"] = api_url
    raw["cloud"]["device_token"] = device_token

    with open(CONFIG_FILE, "w") as f:
        yaml.dump(raw, f, default_flow_style=False)
    CONFIG_FILE.chmod(0o600)

    print(f"Device registered successfully.")
    print(f"Restarting screenwarden daemon...")
    subprocess.run(["systemctl", "restart", "screenwarden"])
    print(f"Done. Cloud sync is now active.")


def main():
    parser = argparse.ArgumentParser(prog="screenwarden")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("install", help="Install and configure screenwarden")
    sub.add_parser("status", help="Show service status")

    register_parser = sub.add_parser("register", help="Register this device with the cloud app")
    register_parser.add_argument("code", help="Pairing code from the screenwarden web app (e.g. SW-ABC123)")

    args = parser.parse_args()

    if args.command == "install":
        cmd_install(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "register":
        cmd_register(args)
    else:
        parser.print_help()
```

- [ ] **Step 2: Verify CLI --help shows register command**

```bash
.venv/bin/python -m screenwarden.cli.main --help
```

Expected: output includes `register` subcommand.

- [ ] **Step 3: Verify register --help shows code argument**

```bash
.venv/bin/python -m screenwarden.cli.main register --help
```

Expected: shows `code` positional argument.

- [ ] **Step 4: Run full test suite**

```bash
.venv/bin/pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/screenwarden/cli/main.py
git commit -m "feat: add 'screenwarden register <CODE>' CLI command for cloud pairing"
```

---

## Self-Review

**Spec coverage:**
- [x] `CloudConfig` dataclass + `cloud:` section parsed in `Config.load()` — Task 1
- [x] `CloudConfig` defaults when section absent — Task 1 (test + implementation)
- [x] `SyncResult` dataclass — Task 2
- [x] `CloudSync.sync()` — correct payload, commands returned, empty on network error, empty on non-200 — Task 2
- [x] `CloudSync.register()` — returns device_token, raises RuntimeError on 404 — Task 2
- [x] urllib.request used (no new deps) — Task 2
- [x] 5-second timeout on sync — Task 2 (`timeout=5`)
- [x] CloudSync initialised in main.py if device_token set — Task 3
- [x] Cloud sync step in tick loop after local enforcement — Task 3
- [x] grant commands written to DB via `db.add_time_grant` — Task 3
- [x] config_change commands update `config.users` and `trackers[u]._config` — Task 3
- [x] config updates from response body applied in-memory — Task 3
- [x] All cloud errors swallowed, never propagate to main loop — Task 3
- [x] `DEFAULT_CONFIG` gains `cloud:` section with empty `device_token` — Task 4
- [x] `register` subcommand reads api_url from config, calls `CloudSync.register`, writes `device_token` back, restarts daemon — Task 4
- [x] `install` output hints about `register` command — Task 4

**Placeholder scan:** None found.

**Type consistency:** `UserConfig` used in Task 1 and Task 3 — same import path `from screenwarden.daemon.config import Config, UserConfig`. `CloudSync` defined in Task 2, imported in Task 3 and Task 4 — consistent. `SyncResult.commands` and `.config` used in Task 3 match Task 2 definition.
