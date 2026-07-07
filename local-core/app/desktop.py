"""Desktop launcher: runs the Local Core as a local app.

Starts the FastAPI server on localhost in a background thread and opens a native
window (pywebview) pointing at the dashboard. Falls back to the default browser
if pywebview isn't installed. This is the entry point packaged for Windows.

Run:  strikee-core         (after `pip install -e ".[desktop]"`)
  or:  python run_desktop.py
"""
from __future__ import annotations

import os
import socket
import threading
import time
import webbrowser

from .main import create_app

HOST = "127.0.0.1"


def make_server(app, host: str, port: int):
    import uvicorn
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    return uvicorn.Server(config)


def free_port() -> int:
    s = socket.socket()
    s.bind((HOST, 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_until_up(host: str, port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def start_server_thread(server):
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return thread


def main() -> None:
    port = int(os.environ.get("STRIKEE_PORT", "8760"))
    app = create_app()
    server = make_server(app, HOST, port)
    thread = start_server_thread(server)
    if not wait_until_up(HOST, port):
        raise RuntimeError("Local Core server did not start")

    url = f"http://{HOST}:{port}/"
    try:
        import webview  # pywebview
        webview.create_window("Strikee Vision — Local Core", url,
                              width=1280, height=860)
        webview.start()
    except Exception:
        webbrowser.open(url)
        print(f"Strikee Vision — Local Core running at {url}  (Ctrl-C to stop)")
        try:
            while thread.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
    server.should_exit = True


if __name__ == "__main__":
    main()
