"""M5: rule templates, notification engine (matching/cooldown/tiered), and API."""
from app.db import Database
from app.notify import RULE_TEMPLATES, NotificationEngine
from app.store import (
    EventStore, NotificationStore, RuleStore, SessionStore,
)
from app.pipeline.sink import ChangeEvent, DbStateSink
from app.pipeline.types import AssetSnapshot
from app.repository import Repository
from app.entities import REGISTRY


def _rule(db, venue_id, template_type, params, **kw):
    spec = next(s for s in REGISTRY if s.name == "rule")
    with db.cursor() as cur:
        return Repository(spec).create(cur, {
            "venue_id": venue_id, "name": kw.get("name", template_type),
            "template_type": template_type, "params": params,
            "severity": kw.get("severity", "warning"),
            "cooldown_sec": kw.get("cooldown_sec", 300),
            "channel": kw.get("channel", "in_app"),
        })


def _event(label="Degraded", prev="Occupied", health="degraded", asset="a1", etype="state_change"):
    return {"id": "e1", "type": etype, "asset_id": asset, "business_unit_id": "bu1",
            "label": label, "prev_label": prev, "health": health}


def test_rule_templates_catalog():
    assert "label_became" in RULE_TEMPLATES
    assert "health_became" in RULE_TEMPLATES


def test_label_became_matches_and_creates():
    db = Database(":memory:")
    _rule(db, "v1", "label_became", {"label": "Degraded"})
    eng = NotificationEngine(RuleStore(db), NotificationStore(db),
                             clock=lambda: "2026-07-07T10:00:00+00:00")
    created = eng.on_event("v1", _event(label="Degraded"))
    assert len(created) == 1
    assert created[0]["severity"] == "warning"
    assert created[0]["status"] == "delivered"       # in_app -> delivered
    db.close()


def test_no_match_when_label_differs():
    db = Database(":memory:")
    _rule(db, "v1", "label_became", {"label": "Degraded"})
    eng = NotificationEngine(RuleStore(db), NotificationStore(db),
                             clock=lambda: "2026-07-07T10:00:00+00:00")
    assert eng.on_event("v1", _event(label="Available", prev="Occupied")) == []
    db.close()


def test_cooldown_suppresses_repeat():
    db = Database(":memory:")
    _rule(db, "v1", "health_became", {"health": "offline"}, cooldown_sec=300)
    # default (real) clock so notification timestamps and cooldown agree; two
    # rapid events fall inside the 300s window.
    eng = NotificationEngine(RuleStore(db), NotificationStore(db))
    ev = _event(label="Unknown", prev="Occupied", health="offline")
    assert len(eng.on_event("v1", ev)) == 1
    assert len(eng.on_event("v1", ev)) == 0          # suppressed by cooldown
    assert len(NotificationStore(db).list("v1")) == 1
    db.close()


def test_network_channel_is_queued_not_delivered():
    db = Database(":memory:")
    _rule(db, "v1", "label_became", {"label": "Degraded"}, channel="email")
    eng = NotificationEngine(RuleStore(db), NotificationStore(db),
                             clock=lambda: "2026-07-07T10:00:00+00:00")
    n = eng.on_event("v1", _event(label="Degraded"))[0]
    assert n["channel"] == "email"
    assert n["status"] == "pending"                  # best-effort, queued
    db.close()


def test_disabled_rule_does_not_fire():
    db = Database(":memory:")
    _rule(db, "v1", "label_became", {"label": "Degraded"})
    # disable it
    spec = next(s for s in REGISTRY if s.name == "rule")
    rules = RuleStore(db).list_enabled("v1")
    with db.cursor() as cur:
        Repository(spec).update(cur, rules[0]["id"], {"enabled": False})
    eng = NotificationEngine(RuleStore(db), NotificationStore(db),
                             clock=lambda: "2026-07-07T10:00:00+00:00")
    assert eng.on_event("v1", _event(label="Degraded")) == []
    db.close()


def test_sink_creates_notification_on_state_change():
    db = Database(":memory:")
    _rule(db, "v1", "label_became", {"label": "Degraded"})
    notifier = NotificationEngine(RuleStore(db), NotificationStore(db),
                                  clock=lambda: "2026-07-07T10:00:00+00:00")
    sink = DbStateSink(EventStore(db), SessionStore(db), notifier)
    snap = AssetSnapshot(asset_id="a1", name="T1", business_unit_id="bu1",
                         presence="unknown", activity="unknown", health="degraded",
                         label="Degraded", confidence=0.2,
                         effective_at="2026-07-07T10:00:00+00:00")
    sink.handle("v1", [ChangeEvent("Occupied", snap)])
    assert len(NotificationStore(db).list("v1")) == 1
    db.close()


def test_notification_ack_resolve_and_review_queue(client):
    db = client.app.state.db
    ns = NotificationStore(db)
    n = ns.create({"venue_id": "v1", "severity": "warning", "status": "delivered",
                   "channel": "in_app", "title": "Camera offline"})
    # ack
    r = client.post(f"/api/notifications/{n['id']}/ack", json={"actor": "mgr"})
    assert r.json()["status"] == "acknowledged"
    # review queue counts it while unresolved
    q = client.get("/api/venues/v1/review-queue").json()
    assert q["total"] >= 1
    # resolve
    r = client.post(f"/api/notifications/{n['id']}/resolve", json={"actor": "mgr"})
    assert r.json()["status"] == "resolved"
    assert client.post("/api/notifications/nope/ack").status_code == 404


def test_rule_crud_via_registry(client):
    org = client.post("/api/organizations", json={"name": "X"}).json()
    v = client.post("/api/venues", json={"organization_id": org["id"], "name": "C"}).json()
    r = client.post("/api/rules", json={
        "venue_id": v["id"], "name": "Camera offline",
        "template_type": "health_became", "severity": "critical",
        "params": {"health": "offline"},
    })
    assert r.status_code == 201
    rule = r.json()
    assert rule["template_type"] == "health_became"
    assert rule["params"] == {"health": "offline"}
    assert rule["enabled"] is True
    assert len(client.get(f"/api/rules?venue_id={v['id']}").json()) == 1
