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

    def tick(self, active: bool, now: datetime, today: date):
        if active:
            self._db.add_usage_seconds(self._username, today, TICK_INTERVAL_SECONDS)

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
