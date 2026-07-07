"""App factory for the Strikee Vision Local Core.

create_app(db_path) wires the database, health endpoint, config CRUD routers,
and the minimal dashboard shell. Run locally with:

    uvicorn app.main:app --reload
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from . import __version__
from .api import all_routers
from .db import Database
from .entities import REGISTRY
from .pipeline.broadcast import Broadcaster
from .pipeline.manager import PerceptionUnavailable, RuntimeManager

WEB_DIR = Path(__file__).parent.parent / "web"


def create_app(db_path: str | None = None) -> FastAPI:
    db_path = db_path or os.environ.get("STRIKEE_DB", "strikee.db")
    interval = float(os.environ.get("STRIKEE_TICK_SEC", "7"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await app.state.runtime.stop_all()

    app = FastAPI(title="Strikee Vision Local Core", version=__version__,
                  lifespan=lifespan)
    app.state.db = Database(db_path)
    app.state.broadcaster = Broadcaster()
    app.state.runtime = RuntimeManager(app.state.db, app.state.broadcaster, interval)

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

    # --- live pipeline control (M2) ---------------------------------------

    @app.post("/api/venues/{venue_id}/pipeline/start")
    async def pipeline_start(venue_id: str):
        try:
            return await app.state.runtime.start(venue_id)
        except PerceptionUnavailable as exc:
            raise HTTPException(503, str(exc))

    @app.post("/api/venues/{venue_id}/pipeline/stop")
    async def pipeline_stop(venue_id: str):
        return await app.state.runtime.stop(venue_id)

    @app.get("/api/venues/{venue_id}/pipeline/status")
    def pipeline_status(venue_id: str):
        return app.state.runtime.status(venue_id)

    @app.websocket("/ws/venues/{venue_id}")
    async def ws_venue(websocket: WebSocket, venue_id: str):
        await websocket.accept()
        bcast = app.state.broadcaster
        bcast.add(venue_id, websocket)
        # send current state immediately, if a runtime exists
        rt = app.state.runtime.get(venue_id)
        if rt is not None:
            await bcast.send_to(websocket, venue_id, rt.current_snapshots())
        try:
            while True:
                await websocket.receive_text()  # keep-alive; ignore inbound
        except WebSocketDisconnect:
            pass
        finally:
            bcast.remove(venue_id, websocket)

    @app.get("/", response_class=HTMLResponse)
    def dashboard():
        index = WEB_DIR / "index.html"
        if index.exists():
            return index.read_text()
        return "<h1>Strikee Vision Local Core</h1><p>Dashboard shell not found.</p>"

    return app


app = create_app()
