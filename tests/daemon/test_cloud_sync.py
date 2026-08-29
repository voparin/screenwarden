import json
import pytest
from datetime import date
from unittest.mock import patch, MagicMock
from urllib.error import URLError
from screenwarden.daemon.cloud_sync import CloudSync, SyncResult


API_URL = "https://screenwarden-cloud.onrender.com"
TOKEN = "abc123devicetoken"


def make_response(body: dict, status: int = 200):
    mock = MagicMock()
    mock.status = status
    mock.read.return_value = json.dumps(body).encode()
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    return mock


def test_sync_sends_correct_payload():
    cs = CloudSync(API_URL, TOKEN)
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["method"] = req.method
        captured["token"] = req.get_header("X-device-token")
        body = json.loads(req.data.decode())
        captured["body"] = body
        return make_response({"commands": [], "config": {}})

    with patch("screenwarden.daemon.cloud_sync.urllib.request.urlopen", fake_urlopen):
        cs.sync(users={"jakob": 3600}, today=date(2026, 8, 29))

    assert captured["url"] == f"{API_URL}/sync"
    assert captured["method"] == "POST"
    assert captured["token"] == TOKEN
    assert len(captured["body"]["users"]) == 1
    assert captured["body"]["users"][0]["username"] == "jakob"
    assert captured["body"]["users"][0]["total_seconds"] == 3600
    assert captured["body"]["users"][0]["date"] == "2026-08-29"


def test_sync_returns_commands_and_config():
    cs = CloudSync(API_URL, TOKEN)
    response_body = {
        "commands": [
            {"id": "cmd-1", "username": "jakob", "type": "grant", "payload": {"extra_seconds": 900}}
        ],
        "config": {
            "jakob": {"daily_limit_minutes": 90, "warning_minutes": 5, "grace_minutes": 3}
        },
    }
    with patch("screenwarden.daemon.cloud_sync.urllib.request.urlopen",
               return_value=make_response(response_body)):
        result = cs.sync(users={"jakob": 0}, today=date(2026, 8, 29))

    assert len(result.commands) == 1
    assert result.commands[0]["type"] == "grant"
    assert result.config["jakob"]["daily_limit_minutes"] == 90


def test_sync_returns_empty_on_network_error():
    cs = CloudSync(API_URL, TOKEN)
    with patch("screenwarden.daemon.cloud_sync.urllib.request.urlopen",
               side_effect=URLError("connection refused")):
        result = cs.sync(users={"jakob": 0}, today=date(2026, 8, 29))

    assert result.commands == []
    assert result.config == {}


def test_sync_returns_empty_on_non_200():
    cs = CloudSync(API_URL, TOKEN)
    with patch("screenwarden.daemon.cloud_sync.urllib.request.urlopen",
               return_value=make_response({}, status=401)):
        result = cs.sync(users={"jakob": 0}, today=date(2026, 8, 29))

    assert result.commands == []
    assert result.config == {}


def test_register_returns_device_token():
    cs = CloudSync(API_URL, TOKEN)
    with patch("screenwarden.daemon.cloud_sync.urllib.request.urlopen",
               return_value=make_response({"device_token": "newtoken123"})):
        token = cs.register("SW-ABC123", "jakob-laptop")

    assert token == "newtoken123"


def test_register_raises_on_404():
    cs = CloudSync(API_URL, TOKEN)
    from urllib.error import HTTPError
    with patch("screenwarden.daemon.cloud_sync.urllib.request.urlopen",
               side_effect=HTTPError(None, 404, "Not Found", {}, None)):
        with pytest.raises(RuntimeError, match="not found or expired"):
            cs.register("SW-BADCODE", "jakob-laptop")
