"""Venue rename and delete-for-real.

The interesting case is not the venue row - that cascades. It is the five
history tables (events, sessions, metric_samples, rules, notifications) that
carry a bare `venue_id` with no foreign key, so nothing removes them
automatically and their rows keep answering venue-scoped queries after the
venue is gone.
"""
from app.admin import purge_venue, rename_venue, venue_contents


def _org(client, name="Acme"):
    return client.post("/api/organizations", json={"name": name}).json()


def _venue(client, org_id, name="Strikee Club"):
    return client.post("/api/venues", json={
        "organization_id": org_id, "name": name, "timezone": "Asia/Kolkata",
    }).json()


def _history_rows(db, table, venue_id):
    with db.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table} WHERE venue_id = ?", (venue_id,))
        return int(cur.fetchone()[0])


def _seed_history(db, venue_id, asset_id=None, n=3):
    """Write a row into every history table for this venue."""
    from app.store import EventStore, MetricStore, NotificationStore, SessionStore
    events, sessions = EventStore(db), SessionStore(db)
    for i in range(n):
        events.append({"venue_id": venue_id, "asset_id": asset_id,
                       "type": "state_change", "ts": f"2026-08-25T10:0{i}:00+00:00",
                       "origin": "system"})
        s = sessions.open(venue_id, asset_id or f"a{i}", None,
                          start_ts=f"2026-08-25T10:0{i}:00+00:00", confidence=0.9)
        sessions.close(s["id"], end_ts=f"2026-08-25T10:1{i}:00+00:00")
    MetricStore(db).record(venue_id, "2026-08-25T10:00:00+00:00",
                           [{"asset_id": asset_id or "a0", "metric": "reds", "value": 15}])
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO rules (id, venue_id, name, template_type, created_at, "
            "updated_at) VALUES (?,?,?,?,?,?)",
            (f"rule-{venue_id}", venue_id, "r", "label_became",
             "2026-08-25T10:00:00+00:00", "2026-08-25T10:00:00+00:00"))
    NotificationStore(db).create({"venue_id": venue_id, "rule_id": f"rule-{venue_id}",
                                  "title": "t", "severity": "warning"})


# --------------------------------------------------------------------------- delete


def test_purge_removes_history_that_cascade_leaves_behind(client):
    db = client.app.state.db
    org = _org(client)
    v = _venue(client, org["id"])
    _seed_history(db, v["id"])

    for table in ("events", "sessions", "metric_samples", "rules", "notifications"):
        assert _history_rows(db, table, v["id"]) > 0, f"{table} not seeded"

    result = purge_venue(db, v["id"], snapshot_dir="does-not-exist")
    assert result is not None
    assert result["venue"]["name"] == "Strikee Club"
    assert result["removed"]["events"] == 3
    assert result["removed"]["sessions"] == 3

    for table in ("events", "sessions", "metric_samples", "rules", "notifications"):
        assert _history_rows(db, table, v["id"]) == 0, f"{table} orphaned"
    assert client.get(f"/api/venues/{v['id']}").status_code == 404


def test_purge_leaves_other_venues_untouched(client):
    db = client.app.state.db
    org = _org(client)
    keep = _venue(client, org["id"], name="Keep")
    drop = _venue(client, org["id"], name="Drop")
    _seed_history(db, keep["id"])
    _seed_history(db, drop["id"])

    purge_venue(db, drop["id"], snapshot_dir="does-not-exist")

    assert _history_rows(db, "events", keep["id"]) == 3
    assert _history_rows(db, "sessions", keep["id"]) == 3
    assert client.get(f"/api/venues/{keep['id']}").status_code == 200


def test_purge_deletes_snapshot_directory(client, tmp_path):
    db = client.app.state.db
    org = _org(client)
    v = _venue(client, org["id"])
    snaps = tmp_path / v["id"] / "2026-08-25"
    snaps.mkdir(parents=True)
    (snaps / "table1_120000.jpg").write_bytes(b"jpeg")
    (snaps / "table1_130000.jpg").write_bytes(b"jpeg")

    result = purge_venue(db, v["id"], snapshot_dir=str(tmp_path))

    assert result["removed"]["snapshots"] == 2
    assert not (tmp_path / v["id"]).exists()


def test_purge_unknown_venue_returns_none(client):
    assert purge_venue(client.app.state.db, "nope", snapshot_dir="x") is None


def test_contents_reports_without_deleting(client):
    db = client.app.state.db
    org = _org(client)
    v = _venue(client, org["id"])
    _seed_history(db, v["id"])

    info = venue_contents(db, v["id"], snapshot_dir="does-not-exist")
    assert info["venue"]["name"] == "Strikee Club"
    assert info["counts"]["events"] == 3
    # nothing removed
    assert _history_rows(db, "events", v["id"]) == 3
    assert client.get(f"/api/venues/{v['id']}").status_code == 200


def test_delete_route_reports_what_it_removed(client):
    db = client.app.state.db
    org = _org(client)
    v = _venue(client, org["id"])
    _seed_history(db, v["id"])

    r = client.delete(f"/api/venues/{v['id']}")
    assert r.status_code == 200
    assert r.json()["removed"]["events"] == 3
    assert client.delete(f"/api/venues/{v['id']}").status_code == 404


def test_contents_route(client):
    org = _org(client)
    v = _venue(client, org["id"])
    r = client.get(f"/api/venues/{v['id']}/contents")
    assert r.status_code == 200
    assert r.json()["counts"]["assets"] == 0
    assert client.get("/api/venues/nope/contents").status_code == 404


# --------------------------------------------------------------------------- rename


def test_rename_also_renames_the_organization_created_with_it(client):
    """field_setup names the org after the venue, so a venue-only rename would
    leave a stale org name that later name-matching would trip over."""
    db = client.app.state.db
    org = _org(client, name="Strikee Club")
    v = _venue(client, org["id"], name="Strikee Club")

    result = rename_venue(db, v["id"], "Strikee Club Andheri")

    assert result["name"] == "Strikee Club Andheri"
    assert result["previous_name"] == "Strikee Club"
    assert result["organization_renamed"] is True
    assert client.get(f"/api/organizations/{org['id']}").json()["name"] == "Strikee Club Andheri"


def test_rename_leaves_an_unrelated_organization_name_alone(client):
    db = client.app.state.db
    org = _org(client, name="Elixir Holdings")
    v = _venue(client, org["id"], name="Strikee Club")

    result = rename_venue(db, v["id"], "Strikee Club Andheri")

    assert result["organization_renamed"] is False
    assert client.get(f"/api/organizations/{org['id']}").json()["name"] == "Elixir Holdings"


def test_rename_rejects_blank_and_unknown(client):
    db = client.app.state.db
    org = _org(client)
    v = _venue(client, org["id"])
    try:
        rename_venue(db, v["id"], "   ")
        assert False, "blank name should raise"
    except ValueError:
        pass
    assert rename_venue(db, "nope", "X") is None


def test_rename_route(client):
    org = _org(client, name="Strikee Club")
    v = _venue(client, org["id"], name="Strikee Club")

    r = client.post(f"/api/venues/{v['id']}/rename", json={"name": "Night Owl Club"})
    assert r.status_code == 200
    assert r.json()["name"] == "Night Owl Club"
    assert client.get(f"/api/venues/{v['id']}").json()["name"] == "Night Owl Club"

    assert client.post(f"/api/venues/{v['id']}/rename",
                       json={"name": "  "}).status_code == 422
    assert client.post("/api/venues/nope/rename",
                       json={"name": "X"}).status_code == 404


# ----------------------------------------------------------------- dashboard


def test_dashboard_exposes_the_admin_controls(client):
    """The routes are useless if the page can't reach them, and index.html is
    served as a file - a broken edit there is invisible to every other test."""
    body = client.get("/").text
    assert 'id="renameBtn"' in body
    assert 'id="deleteBtn"' in body
    assert "/rename" in body
    assert "/contents" in body, "delete should confirm using the contents route"


def test_dashboard_html_is_utf8_decodable(client):
    """Guards the Windows regression: index.html is read with an explicit
    encoding, so a non-ASCII character must not break serving it."""
    r = client.get("/")
    assert r.status_code == 200
    assert len(r.text) > 1000
