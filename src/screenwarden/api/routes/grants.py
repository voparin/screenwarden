from datetime import datetime
from fastapi import APIRouter, Depends, Form
from fastapi.responses import RedirectResponse
from screenwarden.daemon.db import Database
from screenwarden.daemon.config import Config


def make_router(db: Database, config: Config, auth):
    router = APIRouter()

    @router.post("/grants")
    def post_grant(
        minutes: int = Form(...),
        reason: str = Form(""),
        _: str = Depends(auth),
    ):
        username = next(iter(config.users))
        db.add_time_grant(
            username,
            datetime.now(),
            minutes * 60,
            reason or None,
        )
        return RedirectResponse("/", status_code=303)

    return router
