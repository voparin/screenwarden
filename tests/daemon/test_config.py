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
