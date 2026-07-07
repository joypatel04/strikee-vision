"""Shared pipeline data types. No heavy dependencies."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# A frame is opaque to the core (an np.ndarray in the OpenCV/YOLO path, or a
# sentinel token in tests). Only concrete Detectors interpret it.
Frame = Any

# Facet value constants
PRESENCE_ABSENT = "absent"
PRESENCE_PRESENT = "present"
PRESENCE_UNKNOWN = "unknown"

ACTIVITY_ACTIVE = "active"
ACTIVITY_INACTIVE = "inactive"
ACTIVITY_UNKNOWN = "unknown"

HEALTH_OK = "ok"
HEALTH_DEGRADED = "degraded"
HEALTH_OFFLINE = "offline"

ROLE_PRIMARY = "primary"
ROLE_SUPPORTING = "supporting"


@dataclass
class Detection:
    """One detected object: bounding box (x1,y1,x2,y2) + confidence + label.
    label defaults to 'person' for backward compatibility with the person path;
    the snooker detector sets labels like 'red_ball', 'game_start', etc."""
    bbox: tuple[float, float, float, float]
    confidence: float
    label: str = "person"


@dataclass
class SensorRuntime:
    """A sensor as the pipeline needs it: what to look at, where, and how."""
    id: str
    asset_id: str
    source_id: Optional[str]
    kind: str                      # occupancy | activity | ...
    role: str = ROLE_PRIMARY       # primary | supporting
    conf_threshold: float = 0.35
    zone_polygons: list = field(default_factory=list)  # [[[x,y],...], ...]


@dataclass
class AssetRuntime:
    id: str
    name: str
    business_unit_id: Optional[str]
    sensors: list[SensorRuntime] = field(default_factory=list)


@dataclass
class SourceRuntime:
    id: str
    name: str
    uri: Optional[str]
    sensors: list[SensorRuntime] = field(default_factory=list)


@dataclass
class RawObservation:
    """One tick's raw read from a single sensor."""
    present: bool
    confidence: float
    count: int = 0          # persons in zone (for occupancy metrics)
    active: bool = False    # movement detected this tick (activity facet)


@dataclass
class AssetSnapshot:
    """The derived, broadcastable state of one asset."""
    asset_id: str
    name: str
    business_unit_id: Optional[str]
    presence: str
    activity: str
    health: str
    label: str
    confidence: float
    effective_at: str

    def to_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "name": self.name,
            "business_unit_id": self.business_unit_id,
            "presence": self.presence,
            "activity": self.activity,
            "health": self.health,
            "label": self.label,
            "confidence": round(self.confidence, 3),
            "effective_at": self.effective_at,
        }
