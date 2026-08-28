from datetime import date
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from screenwarden.daemon.db import Database
from screenwarden.daemon.config import Config

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def fmt_seconds(seconds: int) -> str:
    h, m = divmod(seconds // 60, 60)
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def make_router(db: Database, config: Config, auth):
    router = APIRouter()
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @router.get("/", response_class=HTMLResponse)
    def today(request: Request, _: str = Depends(auth)):
        username = next(iter(config.users))
        user_cfg = config.users[username]
        used = db.get_usage_today(username, date.today())
        limit = user_cfg.daily_limit_seconds
        remaining = max(0, limit - used)
        return templates.TemplateResponse(request, "today.html", {
            "used_fmt": fmt_seconds(used),
            "limit_fmt": fmt_seconds(limit),
            "remaining_fmt": fmt_seconds(remaining),
        })

    return router
