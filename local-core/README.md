# Strikee Vision — Local Core

The on-site engine + local dashboard. Runs entirely on the venue's Windows box.
See the [build blueprint](../docs/engineering/01-build-blueprint.md) for the full
architecture and milestone plan.

**Milestone M1 (this):** configuration skeleton — SQLite schema, config CRUD API
for the domain chain (Organization → Venue → Business Unit / Space → Video
Source → Asset Type → Asset → Zone → Sensor), FastAPI app, and a dashboard shell.
Runtime pipeline (perception → state → events → sessions → metrics) lands in
M2–M4.

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

- Dashboard shell: http://localhost:8000/
- Health: http://localhost:8000/health
- Interactive API docs: http://localhost:8000/docs

The database file defaults to `strikee.db` (override with `STRIKEE_DB`).

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
  main.py          app factory, /health, dashboard shell
web/
  index.html       minimal dashboard shell
tests/             pytest (health + config CRUD + model invariants)
```

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
