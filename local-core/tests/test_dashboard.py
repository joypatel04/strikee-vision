"""The dashboard is a static file, so a broken edit in it is invisible to every
other test. These check the things that would silently degrade it."""
import re
from pathlib import Path

HTML = Path(__file__).resolve().parent.parent / "web" / "index.html"


def _page():
    return HTML.read_text(encoding="utf-8")


def test_served(client):
    r = client.get("/")
    assert r.status_code == 200 and len(r.text) > 5000


def test_no_remote_assets():
    """This box's internet can drop while the cameras keep working. A dashboard
    that loses its fonts or scripts when that happens is the wrong dashboard."""
    remote = [u for u in re.findall(r'https?://[^"\')\s]+', _page())
              if "127.0.0.1" not in u and "localhost" not in u]
    assert remote == [], f"dashboard depends on remote assets: {remote}"


def test_entity_urls_use_the_hyphenated_segments(client):
    """business-units, not business_units. The underscore form 404s, and the
    failure is silent - every asset just shows as Unassigned."""
    page = _page()
    for wrong in ("/api/business_units", "/api/asset_types", "/api/video_sources"):
        assert wrong not in page, f"{wrong} would 404"
    assert "/api/business-units" in page


def test_every_endpoint_it_calls_actually_exists(client):
    """Catches a renamed route before it becomes an empty panel."""
    page = _page()
    venue = client.post("/api/venues", json={
        "organization_id": client.post("/api/organizations",
                                       json={"name": "T"}).json()["id"],
        "name": "T"}).json()["id"]

    for path in ["/health", "/api/venues", "/api/sync-health", "/api/system-health",
                 "/api/diagnostics", "/api/business-units", "/api/sensors",
                 "/api/assets"]:
        assert path in page, f"dashboard no longer calls {path}"
        assert client.get(path).status_code == 200, f"{path} is broken"

    for suffix in [f"/api/venues/{venue}/sessions?limit=30",
                   f"/api/venues/{venue}/events?limit=30",
                   f"/api/venues/{venue}/notifications?limit=30",
                   f"/api/venues/{venue}/games?date=2026-08-27",
                   f"/api/venues/{venue}/contents",
                   f"/api/venues/{venue}/pipeline/status"]:
        assert client.get(suffix).status_code == 200, f"{suffix} is broken"


def test_javascript_has_balanced_delimiters():
    js = re.search(r"<script>(.*)</script>", _page(), re.S).group(1)
    for open_c, close_c in ("{}", "()", "[]"):
        assert js.count(open_c) == js.count(close_c), f"unbalanced {open_c}{close_c}"


def test_features_are_present():
    page = _page()
    for feature, marker in [
        ("venue admin", 'id="renameBtn"'),
        ("venue delete", 'id="deleteBtn"'),
        ("fault banner", 'id="faults"'),
        ("system check", 'id="diag"'),
        ("headline numbers", 'id="kpis"'),
        ("business-unit grouping", 'id="units"'),
        ("live websocket", "/ws/venues/"),
        ("evidence snapshots", "/snapshots/"),
    ]:
        assert marker in page, f"{feature} missing from the dashboard"


def test_mobile_viewport_is_declared():
    """It is looked at remotely, often from a phone."""
    assert 'name="viewport"' in _page()


def test_reduced_motion_is_respected():
    assert "prefers-reduced-motion" in _page()
