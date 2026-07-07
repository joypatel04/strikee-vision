"""Notification rule templates + engine.

Rules are instances of a FIXED template catalog (G06 / D015): users tune params
and toggle enabled; there is no free-form logic. Delivery is tiered (G10):
in-app is the guaranteed offline floor (marked delivered immediately); network
channels are best-effort and left 'pending' (queued) — actual delivery is a
later concern.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

# The fixed catalog. Each entry documents its matcher params + sensible defaults.
RULE_TEMPLATES = {
    "label_became": {
        "description": "Notify when an asset's state label becomes a target value.",
        "params": {"label": "Degraded"},
        "default_severity": "warning",
        "default_cooldown_sec": 300,
    },
    "health_became": {
        "description": "Notify when an asset's health facet becomes a target value "
                       "(e.g. a camera goes offline).",
        "params": {"health": "offline"},
        "default_severity": "critical",
        "default_cooldown_sec": 300,
    },
}


def _seconds_between(a_iso: str, b_iso: str) -> float:
    return abs((datetime.fromisoformat(b_iso) - datetime.fromisoformat(a_iso)).total_seconds())


class NotificationEngine:
    """Evaluates enabled rules against state-change events and creates
    notifications, honouring per-rule+asset cooldown."""

    def __init__(self, rule_store, notification_store, broadcaster=None, clock=None):
        self.rules = rule_store
        self.notifs = notification_store
        self.broadcaster = broadcaster
        from .repository import now_iso
        self._clock = clock or now_iso

    def on_event(self, venue_id: str, event: dict) -> list[dict]:
        created = []
        for rule in self.rules.list_enabled(venue_id):
            if not self._matches(rule, event):
                continue
            if self._in_cooldown(rule, event):
                continue
            created.append(self._create(venue_id, rule, event))
        return created

    # -- matching ----------------------------------------------------------

    def _matches(self, rule: dict, event: dict) -> bool:
        if event.get("type") != "state_change":
            return False
        params = rule.get("params") or {}
        t = rule["template_type"]
        if t == "label_became":
            return (event.get("label") == params.get("label")
                    and event.get("prev_label") != event.get("label"))
        if t == "health_became":
            return event.get("health") == params.get("health")
        return False

    def _in_cooldown(self, rule: dict, event: dict) -> bool:
        last = self.notifs.last_created_at(rule["id"], event.get("asset_id"))
        if last is None:
            return False
        return _seconds_between(last, self._clock()) < rule.get("cooldown_sec", 300)

    def _create(self, venue_id: str, rule: dict, event: dict) -> dict:
        channel = rule.get("channel", "in_app")
        # tiered delivery: in-app is always available -> delivered; network -> queued
        status = "delivered" if channel == "in_app" else "pending"
        title = rule.get("name") or rule["template_type"]
        message = f"{event.get('label', '')} — asset {event.get('asset_id', '')}".strip(" —")
        notif = self.notifs.create({
            "venue_id": venue_id,
            "rule_id": rule["id"],
            "event_id": event.get("id"),
            "asset_id": event.get("asset_id"),
            "business_unit_id": event.get("business_unit_id"),
            "severity": rule.get("severity", "warning"),
            "status": status,
            "channel": channel,
            "title": title,
            "message": message,
        })
        return notif
