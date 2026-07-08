"""End-to-end: run the REAL app stack (HTTP -> API -> repository -> SQL) on the
libsql backend, to prove every real query works through the adapter — not just
the isolated adapter unit tests. Uses STRIKEE_LIBSQL_LOCAL (libsql, local file,
no cloud) so it needs no Turso token."""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app

pytest.importorskip("libsql")


@pytest.fixture
def libsql_client(tmp_path, monkeypatch):
    monkeypatch.setenv("STRIKEE_LIBSQL_LOCAL", "1")
    app = create_app(db_path=str(tmp_path / "app.db"))
    assert app.state.db.backend == "libsql-local"      # really on libsql
    with TestClient(app) as c:
        yield c
    app.state.db.close()


def test_crud_lifecycle_on_libsql(libsql_client):
    c = libsql_client
    # create
    org = c.post("/api/organizations", json={"name": "Acme"})
    assert org.status_code == 201
    oid = org.json()["id"]
    # get + update + list
    assert c.get(f"/api/organizations/{oid}").json()["name"] == "Acme"
    assert c.patch(f"/api/organizations/{oid}", json={"name": "Acme Corp"}).json()["name"] == "Acme Corp"
    assert len(c.get("/api/organizations").json()) == 1
    # delete + 404 (exercises the rowcount==0 adapter fix through the HTTP stack)
    assert c.delete(f"/api/organizations/{oid}").status_code == 204
    assert c.get(f"/api/organizations/{oid}").status_code == 404


def test_missing_delete_is_404_on_libsql(libsql_client):
    # the rowcount fix in action: deleting a non-existent row must 404, not 204
    assert libsql_client.delete("/api/venues/nope").status_code == 404


def test_cascade_delete_and_json_roundtrip_on_libsql(libsql_client):
    c = libsql_client
    org = c.post("/api/organizations", json={"name": "Acme"}).json()
    v = c.post("/api/venues", json={
        "organization_id": org["id"], "name": "Club",
        "operating_hours": {"mon": ["10:00", "23:00"]},
    }).json()
    assert v["operating_hours"] == {"mon": ["10:00", "23:00"]}   # JSON column round-trip
    space = c.post("/api/spaces", json={"venue_id": v["id"], "name": "Area"}).json()
    assert len(c.get("/api/spaces").json()) == 1
    # FK cascade must work on libsql too
    assert c.delete(f"/api/venues/{v['id']}").status_code == 204
    assert c.get(f"/api/spaces/{space['id']}").status_code == 404
