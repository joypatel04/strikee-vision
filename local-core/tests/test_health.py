def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body
    # all nine config entities are exposed
    assert set(body["entities"]) == {
        "organizations", "venues", "business-units", "spaces",
        "video-sources", "asset-types", "assets", "zones", "sensors", "rules",
    }


def test_dashboard_shell_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Strikee Vision" in r.text
