"""CRUD + reconciled-model invariants for the config API."""


def _org(client, name="Acme"):
    return client.post("/api/organizations", json={"name": name}).json()


def _venue(client, org_id, name="Strikee Club"):
    return client.post("/api/venues", json={
        "organization_id": org_id, "name": name, "timezone": "Asia/Kolkata",
    }).json()


def test_organization_lifecycle(client):
    # create
    r = client.post("/api/organizations", json={"name": "Acme"})
    assert r.status_code == 201
    org = r.json()
    assert org["name"] == "Acme"
    assert org["id"] and org["created_at"] and org["updated_at"]

    # get
    assert client.get(f"/api/organizations/{org['id']}").json()["name"] == "Acme"

    # update (partial)
    r = client.patch(f"/api/organizations/{org['id']}", json={"name": "Acme Corp"})
    assert r.status_code == 200
    assert r.json()["name"] == "Acme Corp"

    # list
    assert len(client.get("/api/organizations").json()) == 1

    # delete
    assert client.delete(f"/api/organizations/{org['id']}").status_code == 204
    assert client.get(f"/api/organizations/{org['id']}").status_code == 404


def test_missing_returns_404(client):
    assert client.get("/api/venues/nope").status_code == 404
    assert client.patch("/api/venues/nope", json={"name": "x"}).status_code == 404
    assert client.delete("/api/venues/nope").status_code == 404


def test_venue_defaults_and_json_roundtrip(client):
    org = _org(client)
    r = client.post("/api/venues", json={
        "organization_id": org["id"], "name": "Club",
        "operating_hours": {"mon": ["10:00", "23:00"]},
    })
    assert r.status_code == 201
    v = r.json()
    assert v["timezone"] == "UTC"                         # DB default applied
    assert v["operating_hours"] == {"mon": ["10:00", "23:00"]}  # JSON round-trip


def test_list_scoped_by_parent(client):
    org1 = _org(client, "Org1")
    org2 = _org(client, "Org2")
    _venue(client, org1["id"], "V1")
    _venue(client, org1["id"], "V2")
    _venue(client, org2["id"], "V3")

    all_venues = client.get("/api/venues").json()
    assert len(all_venues) == 3

    scoped = client.get(f"/api/venues?organization_id={org1['id']}").json()
    assert {v["name"] for v in scoped} == {"V1", "V2"}


def test_asset_type_session_duration_defaults(client):
    """Reconciled model: Asset Type carries min start / min clear (grace)."""
    org = _org(client)
    v = _venue(client, org["id"])
    at = client.post("/api/asset-types", json={
        "venue_id": v["id"], "name": "Snooker Table",
    }).json()
    assert at["min_start_sec"] == 14
    assert at["min_clear_sec"] == 21


def test_sensor_references_asset_source_zone(client):
    """Reconciled model G01/G02: Sensor owned by Asset, references a Video
    Source (evidence) and a Zone (scope), with a primary/supporting role."""
    org = _org(client)
    v = _venue(client, org["id"])
    space = client.post("/api/spaces", json={"venue_id": v["id"], "name": "Snooker Area"}).json()
    bu = client.post("/api/business-units", json={"venue_id": v["id"], "name": "Snooker", "kind": "snooker"}).json()
    src = client.post("/api/video-sources", json={"venue_id": v["id"], "space_id": space["id"], "name": "Cam A"}).json()
    at = client.post("/api/asset-types", json={"venue_id": v["id"], "name": "Snooker Table"}).json()
    asset = client.post("/api/assets", json={
        "venue_id": v["id"], "space_id": space["id"], "business_unit_id": bu["id"],
        "asset_type_id": at["id"], "name": "Table 1",
    }).json()
    zone = client.post("/api/zones", json={
        "space_id": space["id"], "name": "Table 1 Zone",
        "polygons": [[[0, 0], [10, 0], [10, 10], [0, 10]]],
    }).json()

    r = client.post("/api/sensors", json={
        "asset_id": asset["id"], "video_source_id": src["id"], "zone_id": zone["id"],
        "type": "occupancy", "role": "primary",
    })
    assert r.status_code == 201
    s = r.json()
    assert s["asset_id"] == asset["id"]
    assert s["video_source_id"] == src["id"]
    assert s["zone_id"] == zone["id"]
    assert s["role"] == "primary"
    assert s["conf_threshold"] == 0.35        # default
    assert s["enabled"] is True               # bool round-trip
    assert zone["polygons"] == [[[0, 0], [10, 0], [10, 10], [0, 10]]]


def test_cascade_delete_venue_removes_children(client):
    """FK ON DELETE CASCADE: deleting a Venue removes its Spaces/Assets etc."""
    org = _org(client)
    v = _venue(client, org["id"])
    space = client.post("/api/spaces", json={"venue_id": v["id"], "name": "Area"}).json()

    assert len(client.get("/api/spaces").json()) == 1
    assert client.delete(f"/api/venues/{v['id']}").status_code == 204
    # child space is gone via cascade
    assert client.get(f"/api/spaces/{space['id']}").status_code == 404
    assert len(client.get("/api/spaces").json()) == 0
