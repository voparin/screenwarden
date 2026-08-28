import pytest
from datetime import date
from httpx import AsyncClient, ASGITransport
from screenwarden.api.app import create_app
from screenwarden.daemon.db import Database
from screenwarden.daemon.config import Config, UserConfig


def make_app():
    db = Database(":memory:")
    db.init_schema()
    config = Config.__new__(Config)
    config._path = ""
    config.users = {
        "jakob": UserConfig(daily_limit_minutes=120, warning_minutes=5, grace_minutes=5)
    }
    return create_app(db=db, config=config, password="secret"), db


@pytest.mark.asyncio
async def test_today_shows_usage():
    app, db = make_app()
    db.add_usage_seconds("jakob", date.today(), 3600)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/", auth=("admin", "secret"))
    assert response.status_code == 200
    assert "1h 0m" in response.text


@pytest.mark.asyncio
async def test_today_shows_time_remaining():
    app, db = make_app()
    db.add_usage_seconds("jakob", date.today(), 3600)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/", auth=("admin", "secret"))
    assert response.status_code == 200
    # 120 min limit - 60 min used = 60 min remaining
    assert "1h 0m" in response.text
