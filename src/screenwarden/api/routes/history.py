from fastapi import APIRouter
from screenwarden.daemon.db import Database
from screenwarden.daemon.config import Config


def make_router(db: Database, config: Config, auth):
    router = APIRouter()
    return router
