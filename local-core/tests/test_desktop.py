"""M6: the desktop launcher's server path actually boots and serves."""
import json
import urllib.request

from app.desktop import free_port, make_server, start_server_thread, wait_until_up
from app.main import create_app


def test_desktop_server_boots_and_serves_health():
    port = free_port()
    app = create_app(db_path=":memory:")
    server = make_server(app, "127.0.0.1", port)
    thread = start_server_thread(server)
    try:
        assert wait_until_up("127.0.0.1", port, timeout=15)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as r:
            body = json.load(r)
        assert body["status"] == "ok"
        # dashboard shell is served too
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            assert "Strikee Vision" in r.read().decode()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_wait_until_up_times_out_on_closed_port():
    assert wait_until_up("127.0.0.1", free_port(), timeout=0.5) is False
