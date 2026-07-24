"""起動用。

  python -m uvicorn main:app --reload

で立ち上げて、http://127.0.0.1:8000 を開く。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import inquiries as inquiries_api
from app.api import reports as reports_api
from app.api import reservations as reservations_api
from app.api import users as users_api
from app.config import load_config
from app.db import init_db
from app.web import routes as web_routes

STATIC_DIR = Path(__file__).resolve().parent / "app" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # config.toml の書き間違い（部屋番号の重複など）は、
    # 画面を開く前に起動時点で止めて気づけるようにする。
    load_config()
    init_db()
    yield


app = FastAPI(title="介護施設 業務支援システム", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(reservations_api.router)
app.include_router(users_api.router)
app.include_router(reports_api.router)
app.include_router(inquiries_api.router)
app.include_router(web_routes.router)
