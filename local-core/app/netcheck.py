"""Which network is down: the cameras' or the internet's?

This box sits on two of them. One adapter reaches the DVR, another reaches the
internet, and they fail independently. From inside the app the two failures look
almost identical - grabs stop working - but the fix is completely different, and
telling someone "cameras are failing" when the real answer is "the wifi dongle
fell off the extender" costs an evening.

So test them separately, at the network level, before anything is inferred from
camera behaviour. This works even with the pipeline stopped, which is when
someone is most likely to be standing there wondering why.

TCP connect only - no ping. ICMP is blocked or deprioritised often enough to be
a poor signal, and the DVR answering on 554 is what actually matters.
"""
from __future__ import annotations

import socket
import re
from typing import Optional
from urllib.parse import urlparse

# Reaching *something* on the public internet. Two, so one blocked host does not
# read as an outage. 443 rather than ICMP for the same reason as above.
INTERNET_TARGETS = [("1.1.1.1", 443), ("8.8.8.8", 443)]

_RTSP_DEFAULT_PORT = 554


def reachable(host: str, port: int, timeout: float = 3.0) -> bool:
    """Can we open a TCP connection? Never raises."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def camera_hosts(db) -> list[tuple[str, int]]:
    """The (host, port) of every configured camera, deduplicated.

    Read from the configured sources rather than hardcoded, so it follows the
    DVR if its address ever changes.
    """
    try:
        with db.cursor() as cur:
            cur.execute("SELECT DISTINCT uri FROM video_sources WHERE uri IS NOT NULL")
            uris = [r[0] for r in cur.fetchall()]
    except Exception:
        return []

    out = []
    for uri in uris:
        try:
            parsed = urlparse(uri)
            host = parsed.hostname
            if not host:
                continue
            port = parsed.port or _RTSP_DEFAULT_PORT
            if (host, port) not in out:
                out.append((host, port))
        except Exception:
            continue
    return out


def internet_up(timeout: float = 3.0) -> bool:
    return any(reachable(h, p, timeout) for h, p in INTERNET_TARGETS)


def check(db, timeout: float = 3.0) -> dict:
    """Reachability of both networks, and which cameras answer."""
    hosts = camera_hosts(db)
    results = [(h, p, reachable(h, p, timeout)) for h, p in hosts]
    return {
        "cameras_configured": len(hosts),
        "camera_hosts": [{"host": h, "port": p, "reachable": ok}
                         for h, p, ok in results],
        "cameras_reachable": sum(1 for _, _, ok in results if ok),
        "internet": internet_up(timeout),
    }
