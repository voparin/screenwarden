import pytest
from fastapi.testclient import TestClient
from screenwarden.api.app import create_app
from screenwarden.daemon.db import Database
from screenwarden.daemon.config import Config, UserConfig


def make_test_app(password="secret"):
    db = Database(":memory:")
    db.init_schema()
    config = Config.__new__(Config)
    config._path = ""
    config.users = {
        "jakob": UserConfig(daily_limit_minutes=120, warning_minutes=5, grace_minutes=5)
    }
    app = create_app(db=db, config=config, password=password)
    return app


def test_dashboard_requires_auth():
    client = TestClient(make_test_app(), raise_server_exceptions=False)
    response = client.get("/")
    assert response.status_code == 401


@pytest.mark.skip(reason="route implemented in Task 9")
def test_dashboard_accessible_with_correct_password():
    client = TestClient(make_test_app(password="secret"))
    response = client.get("/", auth=("admin", "secret"))
    assert response.status_code == 200


def test_dashboard_rejects_wrong_password():
    client = TestClient(make_test_app(password="secret"))
    response = client.get("/", auth=("admin", "wrong"))
    assert response.status_code == 401
