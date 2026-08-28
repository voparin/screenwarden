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
                "notify-send 'Screen time warning' '5 minutes left'",
            ],
            capture_output=True,
        )
