import logging
import shlex
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
        cmd = f"notify-send {shlex.quote(title)} {shlex.quote(body)}"
        subprocess.run(
            ["su", "-", self._username, "-c", cmd],
            capture_output=True,
        )
