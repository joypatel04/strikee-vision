"""App factory for the Strikee Vision Local Core.

create_app(db_path) wires the database, health endpoint, config CRUD routers,
and the minimal dashboard shell. Run locally with:

    uvicorn app.main:app --reload
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from . import __version__
from .api import all_routers
from .db import Database
from .entities import REGISTRY

WEB_DIR = Path(__file__).parent.parent / "web"


def create_app(db_path: str | None = None) -> FastAPI:
    db_path = db_path or os.environ.get("STRIKEE_DB", "strikee.db")
    app = FastAPI(title="Strikee Vision Local Core", version=__version__)
    app.state.db = Database(db_path)

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "version": __version__,
            "db": app.state.db.path,
            "entities": [s.plural for s in REGISTRY],
        }

    for router in all_routers():
        app.include_router(router)

    @app.get("/", response_class=HTMLResponse)
    def dashboard():
        index = WEB_DIR / "index.html"
        if index.exists():
            return index.read_text()
        return "<h1>Strikee Vision Local Core</h1><p>Dashboard shell not found.</p>"

    return app


app = create_app()
