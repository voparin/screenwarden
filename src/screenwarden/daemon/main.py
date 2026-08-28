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
    try:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        db = Database(DB_PATH)
        db.init_schema()
    except Exception:
        logger.exception("Failed to initialize database — failing safe (no time granted)")
        raise SystemExit(1)

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
