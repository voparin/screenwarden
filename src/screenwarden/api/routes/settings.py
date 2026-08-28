from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
import yaml
from screenwarden.daemon.db import Database
from screenwarden.daemon.config import Config

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def make_router(db: Database, config: Config, auth):
    router = APIRouter()
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @router.get("/settings", response_class=HTMLResponse)
    def get_settings(request: Request, _: str = Depends(auth)):
        username = next(iter(config.users))
        user_cfg = config.users[username]
        return templates.TemplateResponse(request, "settings.html", {
            "username": username,
            "user_cfg": user_cfg,
        })

    @router.post("/settings")
    def post_settings(
        request: Request,
        daily_limit_minutes: int = Form(...),
        warning_minutes: int = Form(...),
        grace_minutes: int = Form(...),
        _: str = Depends(auth),
    ):
        username = next(iter(config.users))
        # Read existing config to preserve dashboard and other sections
        try:
            with open(config._path) as f:
                raw = yaml.safe_load(f) or {}
        except FileNotFoundError:
            raw = {}

        if "users" not in raw:
            raw["users"] = {}
        raw["users"][username] = {
            "daily_limit_minutes": daily_limit_minutes,
            "warning_minutes": warning_minutes,
            "grace_minutes": grace_minutes,
        }
        with open(config._path, "w") as f:
            yaml.dump(raw, f)
        return RedirectResponse("/settings", status_code=303)

    return router
