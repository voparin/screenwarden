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
