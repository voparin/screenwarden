from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import PlainTextResponse
from pathlib import Path

from screenwarden.api.auth import make_auth_checker
from screenwarden.daemon.db import Database
from screenwarden.daemon.config import Config


def create_app(db: Database, config: Config, password: str) -> FastAPI:
    app = FastAPI(title="screenwarden")
    auth = make_auth_checker(password)

    @app.get("/")
    def dashboard(username: str = Depends(auth)):
        # Placeholder replaced in Task 9 with a real HTML response
        return PlainTextResponse("ok")

    static_dir = Path(__file__).parent.parent.parent.parent / "web" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    from screenwarden.api.routes import today, history, settings, grants
    app.include_router(today.make_router(db, config, auth))
    app.include_router(history.make_router(db, config, auth))
    app.include_router(settings.make_router(db, config, auth))
    app.include_router(grants.make_router(db, config, auth))

    return app
