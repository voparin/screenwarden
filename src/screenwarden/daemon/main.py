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
