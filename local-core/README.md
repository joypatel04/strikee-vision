# Strikee Vision — Local Core

The on-site engine + local dashboard. Runs entirely on the venue's Windows box.
See the [build blueprint](../docs/engineering/01-build-blueprint.md) for the full
architecture and milestone plan.

**M1:** configuration skeleton — SQLite schema, config CRUD API for the domain
chain (Organization → Venue → Business Unit / Space → Video Source → Asset Type
→ Asset → Zone → Sensor), FastAPI app, dashboard shell.

**M2:** live perception → state pipeline. YOLO person detection (pluggable) →
person-in-zone → three-facet state (presence/activity/health) with
primary/supporting fusion and hysteresis smoothing → live asset grid pushed over
WebSocket. Sampled every 5–10s.

**M3:** events + sessions. State changes are persisted as append-only **Events**;
presence transitions open/close **materialized Sessions** (grace window from
presence smoothing). Session **review** (confirm / correct / void) appends
immutable correction events and preserves original times.

**M4:** metric samples + analytics. Periodic scalar samples per asset per tick
feed utilization / occupancy / session analytics by Business Unit.

**M5:** rule templates + tiered notifications. A fixed template catalog
(defaults + ON/OFF) drives notifications; in-app delivers offline, network
channels queue; ack / resolve + a review queue.

**Activity (D-T4):** movement between ticks distinguishes **Active (In Use)**
from **Occupied – Idle**.

**M6:** desktop launcher (`strikee-core`) + Windows packaging — see
[packaging/BUILD.md](packaging/BUILD.md).

The product is feature-complete for a venue field test; detection thresholds,
`motion_threshold`, and `activity_still_ticks` are the tunables to set on real
footage.

The pipeline core (geometry, state engine, runtime) imports **no heavy
libraries** — YOLO and OpenCV sit behind protocols and are used only when a
venue's pipeline is started, so the engine is fully unit-tested with fakes.

## Setup

```bash
cd local-core
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Run

```bash
uvicorn app.main:app --reload
```

- Live dashboard: http://localhost:8000/
- Health: http://localhost:8000/health
- Interactive API docs: http://localhost:8000/docs

Or run it as a **desktop app** (opens a native window; see
[packaging/BUILD.md](packaging/BUILD.md)):

```bash
pip install -e ".[perception,desktop]"
strikee-core
```

Config: `STRIKEE_DB` (db file, default `strikee.db`), `STRIKEE_TICK_SEC`
(sample interval, default 7).

## Running the real pipeline (YOLO)

The detection pipeline needs the heavy extra (torch + OpenCV):

```bash
pip install -e ".[perception]"
```

Then configure a venue's Video Sources (with RTSP `uri`), Assets, Zones (with
`polygons`), and Sensors, and start the pipeline:

```
POST /api/venues/{venue_id}/pipeline/start     # builds YOLO + opens cameras
GET  /api/venues/{venue_id}/pipeline/status
POST /api/venues/{venue_id}/pipeline/stop
WS   /ws/venues/{venue_id}                      # live state snapshots
```

Without the extra installed, `start` returns 503; everything else (config,
dashboard, tests) works without it.

## Test

```bash
pytest
```

Tests use an in-memory SQLite database per test for full isolation.

## Layout

```
app/
  schema.sql       config DDL (reconciled domain model)
  db.py            SQLite connection + schema init
  entities.py      Pydantic write-models + per-entity specs
  repository.py    generic CRUD over SQLite
  api.py           CRUD router factory + get_db dependency
  main.py          app factory, /health, pipeline endpoints, dashboard, WS
  pipeline/
    types.py       Detection / runtime dataclasses / AssetSnapshot
    geometry.py    pure-Python point-in-polygon + ground point
    capture.py     FrameSource protocol + Fake + OpenCV (lazy cv2)
    perception.py  Detector protocol + Fake + YOLO (lazy ultralytics)
    state.py       StateEngine: facets, fusion, smoothing, label
    runtime.py     LiveRuntime tick + DB config loader
    broadcast.py   WebSocket connection manager
    manager.py     RuntimeManager: async tick loops per venue
    sink.py        StateSink: state changes -> events + sessions
  store.py         EventStore (append-only) + SessionStore (materialized)
  review.py        session confirm / correct / void (+ correction events)
  runtime_api.py   events/sessions endpoints + review actions
web/
  index.html       live dashboard (asset grid + sessions + events over WebSocket)
tests/             pytest — config CRUD, geometry, state engine, runtime
                   end-to-end, pipeline HTTP/WS, events/sessions/review (41 tests)
```

## Runtime API (M3)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/venues/{id}/events` | list events (`?asset_id=&limit=`) |
| GET | `/api/venues/{id}/sessions` | list sessions (`?asset_id=&business_unit_id=&limit=`) |
| GET | `/api/sessions/{id}` | get one session |
| POST | `/api/sessions/{id}/confirm` | confirm a detected session |
| POST | `/api/sessions/{id}/correct` | correct start/end (preserves originals) |
| POST | `/api/sessions/{id}/void` | void a false session |

## Config API

Per entity (plural URL segment):

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/{plural}` | create |
| GET | `/api/{plural}` | list (optional parent filters, e.g. `?venue_id=…`) |
| GET | `/api/{plural}/{id}` | get |
| PATCH | `/api/{plural}/{id}` | partial update |
| DELETE | `/api/{plural}/{id}` | delete |

Entities: `organizations`, `venues`, `business-units`, `spaces`,
`video-sources`, `asset-types`, `assets`, `zones`, `sensors`.
