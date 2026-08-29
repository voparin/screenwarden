import json
import logging
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
