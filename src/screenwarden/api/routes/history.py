from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from datetime import date
from screenwarden.daemon.db import Database
from screenwarden.daemon.config import Config

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def make_router(db: Database, config: Config, auth):
    router = APIRouter()
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @router.get("/history", response_class=HTMLResponse)
    def history(request: Request, _: str = Depends(auth)):
        username = next(iter(config.users))
        rows = db.get_usage_last_30_days(username, reference_date=date.today())
        return templates.TemplateResponse(request, "history.html", {
            "rows": rows,
        })

    return router
