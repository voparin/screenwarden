from unittest.mock import patch
import pytest
from screenwarden.daemon.session import SessionDetector


def make_loginctl_output(user: str, session_id: str = "3", seat: str = "seat0") -> str:
    return f"SESSION  UID  USER   SEAT   TTY\n      {session_id} 1000  {user}  {seat}   tty2\n\n1 sessions listed."


def make_empty_loginctl_output() -> str:
    return "SESSION  UID  USER   SEAT   TTY\n\n0 sessions listed."


def test_is_active_returns_true_when_user_has_session():
    detector = SessionDetector("jakob")
    with patch("screenwarden.daemon.session.subprocess.run") as mock_run:
        mock_run.return_value.stdout = make_loginctl_output("jakob")
        mock_run.return_value.returncode = 0
        assert detector.is_active() is True


def test_is_active_returns_false_when_no_sessions():
    detector = SessionDetector("jakob")
    with patch("screenwarden.daemon.session.subprocess.run") as mock_run:
        mock_run.return_value.stdout = make_empty_loginctl_output()
        mock_run.return_value.returncode = 0
        assert detector.is_active() is False


def test_is_active_returns_false_when_different_user():
    detector = SessionDetector("jakob")
    with patch("screenwarden.daemon.session.subprocess.run") as mock_run:
        mock_run.return_value.stdout = make_loginctl_output("anna")
        mock_run.return_value.returncode = 0
        assert detector.is_active() is False


def test_get_session_id_returns_id_for_user():
    detector = SessionDetector("jakob")
    with patch("screenwarden.daemon.session.subprocess.run") as mock_run:
        mock_run.return_value.stdout = make_loginctl_output("jakob", session_id="7")
        mock_run.return_value.returncode = 0
        assert detector.get_session_id() == "7"


def test_get_session_id_returns_none_when_not_active():
    detector = SessionDetector("jakob")
    with patch("screenwarden.daemon.session.subprocess.run") as mock_run:
        mock_run.return_value.stdout = make_empty_loginctl_output()
        mock_run.return_value.returncode = 0
        assert detector.get_session_id() is None
