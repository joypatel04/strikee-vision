"""FastAPI routers: a generic CRUD router per entity, built from its EntitySpec.

Routes per entity (plural URL segment):
    POST   /api/{plural}          create
    GET    /api/{plural}          list (optional parent filters as query params)
    GET    /api/{plural}/{id}     get
    PATCH  /api/{plural}/{id}     update (partial)
    DELETE /api/{plural}/{id}     delete
"""
# NOTE: do NOT add `from __future__ import annotations` here. FastAPI must see
# the dynamically-assigned Pydantic model classes (InModel/UpdateModel) as real
# objects to treat them as request bodies; stringized annotations break that.

from fastapi import APIRouter, Depends, HTTPException, Request

from .db import Database
from .entities import REGISTRY, EntitySpec
from .repository import Repository


def get_db(request: Request) -> Database:
    return request.app.state.db


def build_entity_router(spec: EntitySpec) -> APIRouter:
    router = APIRouter(prefix=f"/api/{spec.plural}", tags=[spec.plural])
    repo = Repository(spec)
    InModel = spec.in_model
    UpdateModel = spec.update_model

    @router.post("", status_code=201)
    def create(payload: InModel, db: Database = Depends(get_db)):  # type: ignore[valid-type]
        with db.cursor() as cur:
            return repo.create(cur, payload.model_dump())

    @router.get("")
    def list_(request: Request, db: Database = Depends(get_db)):
        filters = {p: request.query_params.get(p) for p in spec.parents}
        with db.cursor() as cur:
            return repo.list(cur, filters)

    @router.get("/{rec_id}")
    def get_one(rec_id: str, db: Database = Depends(get_db)):
        with db.cursor() as cur:
            rec = repo.get(cur, rec_id)
        if rec is None:
            raise HTTPException(404, f"{spec.name} not found")
        return rec

    @router.patch("/{rec_id}")
    def update(rec_id: str, payload: UpdateModel, db: Database = Depends(get_db)):  # type: ignore[valid-type]
        data = payload.model_dump(exclude_unset=True)
        with db.cursor() as cur:
            rec = repo.update(cur, rec_id, data)
        if rec is None:
            raise HTTPException(404, f"{spec.name} not found")
        return rec

    @router.delete("/{rec_id}", status_code=204)
    def delete(rec_id: str, db: Database = Depends(get_db)):
        with db.cursor() as cur:
            ok = repo.delete(cur, rec_id)
        if not ok:
            raise HTTPException(404, f"{spec.name} not found")
        return None

    return router


def all_routers() -> list[APIRouter]:
    return [build_entity_router(spec) for spec in REGISTRY]
