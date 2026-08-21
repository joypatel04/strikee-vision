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
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import all_routers
from .db import Database
from .entities import REGISTRY
from .pipeline.broadcast import Broadcaster
from .pipeline.manager import PerceptionUnavailable, RuntimeManager
from .runtime_api import build_runtime_router

WEB_DIR = Path(__file__).parent.parent / "web"


def _maybe_start_backup(db_path: str):
    """If STRIKEE_BACKUP_EVERY_MIN is set and storage is configured, run a
    periodic SQLite→R2/S3 backup in the background. Best-effort; returns the
    task (or None if not enabled) so lifespan can cancel it."""
    import asyncio

    from .backup import BackupConfig, run_once

    every = os.environ.get("STRIKEE_BACKUP_EVERY_MIN")
    cfg = BackupConfig.from_env()
    if not every or not cfg.enabled:
        return None
    period = max(60.0, float(every) * 60.0)

    async def _loop():
        while True:
            await asyncio.sleep(period)
            await asyncio.to_thread(run_once, db_path, cfg)

    return asyncio.get_event_loop().create_task(_loop())


def _maybe_start_turso_sync(db):
    """When the DB is on the Turso backend, replicate the local write-ahead
    changes to the cloud on an interval so the data is queryable from anywhere.
    Best-effort; never blocks writes (they land locally first)."""
    import asyncio

    if getattr(db, "backend", "sqlite3") != "turso":
        return None
    period = max(5.0, float(os.environ.get("STRIKEE_TURSO_SYNC_SEC", "15")))

    async def _loop():
        while True:
            await asyncio.sleep(period)
            await asyncio.to_thread(db.sync)

    return asyncio.get_event_loop().create_task(_loop())


def _autostart_targets(db, spec: str) -> list[str]:
    """Which venue(s) to auto-start. spec='all' -> every configured venue;
    otherwise the given venue id."""
    if spec == "all":
        with db.cursor() as cur:
            cur.execute("SELECT id FROM venues")
            return [r[0] for r in cur.fetchall()]
    return [spec]


async def _run_autostart(runtime, targets: list[str]) -> None:
    """Start each venue's pipeline unattended. Best-effort: a venue that can't
    start (e.g. no perception installed yet) is skipped, not fatal."""
    for venue_id in targets:
        try:
            await runtime.start(venue_id)
        except Exception:
            pass


def _maybe_autostart(app):
    """If STRIKEE_AUTOSTART_VENUE is set, start the pipeline on boot so the venue
    runs with NO manual 'Start pipeline' click — turnkey for staff."""
    import asyncio

    spec = os.environ.get("STRIKEE_AUTOSTART_VENUE")
    if not spec:
        return None
    targets = _autostart_targets(app.state.db, spec)
    if not targets:
        return None
    return asyncio.create_task(_run_autostart(app.state.runtime, targets))


def create_app(db_path: str | None = None) -> FastAPI:
    # Runs before any torch/cv2 import (detectors build lazily on pipeline
    # start), so the Windows OpenMP/HEVC hardening takes effect.
    from .platform_env import harden
    harden()

    db_path = db_path or os.environ.get("STRIKEE_DB", "strikee.db")
    interval = float(os.environ.get("STRIKEE_TICK_SEC", "7"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        backup_task = _maybe_start_backup(db_path)
        sync_task = _maybe_start_turso_sync(app.state.db)
        autostart_task = _maybe_autostart(app)
        yield
        for t in (backup_task, sync_task, autostart_task):
            if t is not None:
                t.cancel()
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

    @app.get("/api/sync-health")
    def sync_health():
        """Cloud-sync health — the dashboard shows 'synced Xs ago' and warns if
        tracking data stops reaching the cloud."""
        return app.state.db.sync_status()

    for router in all_routers():
        app.include_router(router)
    app.include_router(build_runtime_router())

    # serve game-start evidence snapshots
    snap_dir = Path(os.environ.get("STRIKEE_SNAPSHOT_DIR", "snapshots"))
    snap_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/snapshots", StaticFiles(directory=str(snap_dir)), name="snapshots")

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
            return index.read_text(encoding="utf-8")
        return "<h1>Strikee Vision Local Core</h1><p>Dashboard shell not found.</p>"

    return app


app = create_app()
