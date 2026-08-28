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
async def test_post_grant_creates_db_row():
    app, db = make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/grants",
            data={"minutes": "15", "reason": "homework done"},
            auth=("admin", "secret"),
            follow_redirects=False,
        )
    assert response.status_code == 303
    grants = db.get_pending_grants("jakob")
    assert len(grants) == 1
    assert grants[0]["extra_seconds"] == 900


@pytest.mark.asyncio
async def test_post_grant_without_reason():
    app, db = make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/grants",
            data={"minutes": "10", "reason": ""},
            auth=("admin", "secret"),
            follow_redirects=False,
        )
    grants = db.get_pending_grants("jakob")
    assert grants[0]["extra_seconds"] == 600
