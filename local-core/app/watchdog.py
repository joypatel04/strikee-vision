"""System watchdog: notice when the venue box stops working, and say so.

The box has two independent networks and either can fail on its own. One wifi
adapter reaches the DVR; a second reaches the internet. Losing the first stops
tracking entirely while the dashboard still loads perfectly over the second.
Losing the second stops cloud sync while every table on screen keeps updating.
Both failures look like "everything is fine" from the wrong angle, which is
exactly the kind of fault that runs for a week unnoticed.

`check()` turns that into a short list of faults, each with a plain-language
title, what it means, and what to do. `Watchdog` runs it on a timer and records
new faults as notifications so there is a history, with a cooldown so a camera
flapping overnight does not write thousands of rows.

Nothing here ever raises: a watchdog that crashes the process it is watching is
worse than no watchdog.
"""
from __future__ import annotations

import os
import time
from typing import Optional

# A camera is only "down" after this many consecutive failed grabs. One failure
# is normal - a dropped frame, a busy DVR - and the scheduler already backs off.
CAMERA_FAILURE_THRESHOLD = 3

# Match the severity vocabulary the notifications table and dashboard
# already use, so watchdog faults render like every other alert.
ERROR, WARN, INFO = "critical", "warning", "info"


def _fault(key: str, severity: str, title: str, detail: str, action: str) -> dict:
    return {"key": key, "severity": severity, "title": title,
            "detail": detail, "action": action}


def _network_faults(db) -> list[dict]:
    """Which of the two networks is actually down.

    Tested directly rather than inferred from camera failures, so it is right
    even with the pipeline stopped - and it names the adapter, because "cameras
    are failing" sends someone to the DVR when the answer is a dongle that fell
    off the extender.
    """
    from . import netcheck

    try:
        state = netcheck.check(db)
    except Exception:
        return []

    faults: list[dict] = []
    configured = state["cameras_configured"]
    reachable = state["cameras_reachable"]
    hosts = ", ".join(h["host"] for h in state["camera_hosts"]) or "the DVR"

    if configured and reachable == 0:
        if state["internet"]:
            # The distinction that matters: the box is online, so this is not
            # "the internet is down" - it is the camera-side adapter.
            faults.append(_fault(
                "camera-network-down", ERROR,
                "Cannot reach the cameras",
                f"{hosts} does not answer, but this PC does have internet - so "
                "the box is online and it is the camera network that is down. "
                "Nothing is being recorded.",
                "Check the wifi adapter connected to the extender: is it "
                "connected, and does it have a 192.168.0.x address? Then check "
                "the DVR is powered on.",
            ))
        else:
            faults.append(_fault(
                "all-networks-down", ERROR,
                "No network at all",
                f"Neither {hosts} nor the internet answers. Nothing is being "
                "recorded and nothing is syncing.",
                "Check both wifi adapters, then the router.",
            ))
    elif configured and reachable < configured:
        faults.append(_fault(
            "some-cameras-unreachable", WARN,
            f"{configured - reachable} of {configured} camera hosts unreachable",
            "Some cameras answer and some do not, so this is per-DVR rather than "
            "a network fault.",
            "Check the DVR that is not answering.",
        ))
    elif not state["internet"] and configured:
        faults.append(_fault(
            "internet-down", WARN,
            "No internet",
            "The cameras are reachable and recording continues normally. Cloud "
            "sync and snapshot upload are paused and will catch up - nothing is "
            "lost.",
            "Check the wifi adapter on the internet network.",
        ))
    return faults


def check(db, runtime_manager, sync_status=None) -> list[dict]:
    """Current system faults, most severe first. Never raises."""
    faults: list[dict] = list(_network_faults(db))

    # --- cameras: the DVR-facing network ---------------------------------
    try:
        running = runtime_manager.running_venues()
    except Exception:
        running = []

    network_down = any(f["key"] in ("camera-network-down", "all-networks-down")
                       for f in faults)
    for venue_id in running:
        if network_down:
            break          # already reported at the network level; one fault, not N
        try:
            cameras = runtime_manager.capture_status(venue_id)
        except Exception:
            continue
        if not cameras:
            continue
        down = [c for c in cameras
                if c.get("consecutive_failures", 0) >= CAMERA_FAILURE_THRESHOLD]
        if not down:
            continue
        if len(down) == len(cameras):
            # Every camera failing at once is a network fault, not N camera
            # faults - naming it that way points at the right thing to fix.
            faults.append(_fault(
                f"dvr-unreachable:{venue_id}", ERROR,
                "No cameras responding",
                f"All {len(cameras)} cameras have failed "
                f"{CAMERA_FAILURE_THRESHOLD}+ grabs in a row. Tracking has "
                "stopped; nothing is being recorded.",
                "Check the wifi adapter connected to the extender, and that the "
                "DVR is powered on and reachable.",
            ))
        else:
            names = ", ".join(c["source_id"][:8] for c in down[:4])
            faults.append(_fault(
                f"cameras-down:{venue_id}", ERROR,
                f"{len(down)} of {len(cameras)} cameras not responding",
                f"Failing repeatedly: {names}. Those tables are not being "
                "tracked; the rest are unaffected.",
                "Check those channels in the DVR's own web page. The scheduler "
                "keeps retrying, more slowly each time.",
            ))

    # --- cloud sync: the internet-facing network -------------------------
    try:
        sync = sync_status() if sync_status is not None else db.sync_status()
    except Exception:
        sync = None
    internet_down = any(f["key"] in ("internet-down", "all-networks-down")
                        for f in faults)
    if sync and sync.get("sync_enabled") and not sync.get("healthy") and not internet_down:
        age = sync.get("seconds_since_sync")
        age_text = f"{int(age)}s ago" if age is not None else "never"
        faults.append(_fault(
            "sync-stalled", WARN,
            "Not syncing to the cloud",
            f"Last successful sync: {age_text}. Games are still being recorded "
            "locally and will upload once the connection returns - nothing is "
            "lost.",
            "Check the wifi adapter on the internet network.",
        ))

    # --- nothing running at all ------------------------------------------
    if not running:
        # Only a fault if this box is meant to run unattended. Otherwise you
        # stopped it on purpose, and alerting about it is just noise.
        unattended = bool(os.environ.get("STRIKEE_AUTOSTART_VENUE"))
        faults.append(_fault(
            "pipeline-stopped", WARN if unattended else INFO,
            "No pipeline running",
            ("This box is set to start tracking automatically, but nothing is "
             "running." if unattended else "No venue is being tracked right now."),
            "Pick a venue and press Start pipeline.",
        ))

    order = {ERROR: 0, WARN: 1, INFO: 2}
    faults.sort(key=lambda f: order.get(f["severity"], 3))
    return faults


class Watchdog:
    """Runs `check` on a timer and records newly-appeared faults.

    A fault is recorded when it first appears and then not again until its
    cooldown expires, so a camera flapping all night leaves a readable trail
    rather than thousands of rows. Clearing a fault re-arms it immediately -
    the next occurrence is genuinely new and worth knowing about.
    """

    def __init__(self, db, runtime_manager, notification_store=None,
                 cooldown_sec: float = 900.0, clock=time.monotonic,
                 sync_status=None):
        self._db = db
        self._rt = runtime_manager
        self._notifications = notification_store
        self._sync_status = sync_status   # push mode reports its own health
        self._cooldown = cooldown_sec
        self._clock = clock
        self._last_seen: dict[str, float] = {}
        self.faults: list[dict] = []

    def poll(self) -> list[dict]:
        """One pass. Returns the current faults and records the new ones."""
        try:
            faults = check(self._db, self._rt, self._sync_status)
        except Exception:
            return self.faults          # keep the last known state
        now = self._clock()

        current = {f["key"] for f in faults}
        for key in list(self._last_seen):
            if key not in current:
                del self._last_seen[key]      # cleared, so re-arm it

        for fault in faults:
            previous = self._last_seen.get(fault["key"])
            if previous is not None and (now - previous) < self._cooldown:
                continue
            self._last_seen[fault["key"]] = now
            self._record(fault)

        self.faults = faults
        return faults

    def _record(self, fault: dict) -> None:
        # Informational states are shown on the banner but not written to the
        # notification history - that log is for things that need attention.
        if self._notifications is None or fault["severity"] == INFO:
            return
        try:
            self._notifications.create({
                "venue_id": fault["key"].split(":")[-1] if ":" in fault["key"] else "system",
                "title": fault["title"],
                "message": f"{fault['detail']} {fault['action']}",
                "severity": fault["severity"],
            })
        except Exception:
            pass    # a watchdog must never be the reason something goes down
