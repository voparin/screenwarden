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
