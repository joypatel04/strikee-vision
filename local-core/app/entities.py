"""Entity definitions: Pydantic write-models and per-entity table specs.

Each entity has:
  - an `In` model (writable fields, used for create; defaults mirror the DB)
  - an EntitySpec describing table, columns, JSON columns, bool columns, and
    the parent filters allowed on list endpoints.

Read shapes are plain dicts (row + id/created_at/updated_at), serialized by
FastAPI. Update accepts a partial of the In model (all fields optional).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import BaseModel, create_model


# --- write models ----------------------------------------------------------

class OrganizationIn(BaseModel):
    name: str


class VenueIn(BaseModel):
    organization_id: str
    name: str
    timezone: str = "UTC"
    operating_hours: Optional[dict] = None


class BusinessUnitIn(BaseModel):
    venue_id: str
    name: str
    kind: Optional[str] = None


class SpaceIn(BaseModel):
    venue_id: str
    name: str
    parent_space_id: Optional[str] = None


class VideoSourceIn(BaseModel):
    venue_id: str
    name: str
    space_id: Optional[str] = None
    uri: Optional[str] = None
    status: str = "registered"


class AssetTypeIn(BaseModel):
    venue_id: str
    name: str
    min_start_sec: int = 14
    min_clear_sec: int = 21


class AssetIn(BaseModel):
    venue_id: str
    name: str
    space_id: Optional[str] = None
    business_unit_id: Optional[str] = None
    asset_type_id: Optional[str] = None


class ZoneIn(BaseModel):
    space_id: str
    name: str
    polygons: Optional[list] = None


class SensorIn(BaseModel):
    asset_id: str
    video_source_id: Optional[str] = None
    zone_id: Optional[str] = None
    type: str = "occupancy"
    role: str = "primary"
    conf_threshold: float = 0.35
    enabled: bool = True
    params: Optional[dict] = None


def _partial(name: str, model: type[BaseModel]) -> type[BaseModel]:
    """Build an all-optional variant of a write-model for PATCH bodies."""
    fields = {
        key: (Optional[info.annotation], None)
        for key, info in model.model_fields.items()
    }
    return create_model(name, **fields)  # type: ignore[call-overload]


@dataclass
class EntitySpec:
    name: str          # singular, e.g. "venue"
    plural: str        # url segment, e.g. "venues"
    table: str
    in_model: type[BaseModel]
    columns: list[str]                        # writable columns (match in_model)
    parents: dict[str, str] = field(default_factory=dict)  # query param -> column
    json_columns: set[str] = field(default_factory=set)
    bool_columns: set[str] = field(default_factory=set)

    @property
    def update_model(self) -> type[BaseModel]:
        return _partial(f"{self.name.title()}Update", self.in_model)


REGISTRY: list[EntitySpec] = [
    EntitySpec("organization", "organizations", "organizations", OrganizationIn,
               ["name"]),
    EntitySpec("venue", "venues", "venues", VenueIn,
               ["organization_id", "name", "timezone", "operating_hours"],
               parents={"organization_id": "organization_id"},
               json_columns={"operating_hours"}),
    EntitySpec("business_unit", "business-units", "business_units", BusinessUnitIn,
               ["venue_id", "name", "kind"],
               parents={"venue_id": "venue_id"}),
    EntitySpec("space", "spaces", "spaces", SpaceIn,
               ["venue_id", "name", "parent_space_id"],
               parents={"venue_id": "venue_id", "parent_space_id": "parent_space_id"}),
    EntitySpec("video_source", "video-sources", "video_sources", VideoSourceIn,
               ["venue_id", "name", "space_id", "uri", "status"],
               parents={"venue_id": "venue_id", "space_id": "space_id"}),
    EntitySpec("asset_type", "asset-types", "asset_types", AssetTypeIn,
               ["venue_id", "name", "min_start_sec", "min_clear_sec"],
               parents={"venue_id": "venue_id"}),
    EntitySpec("asset", "assets", "assets", AssetIn,
               ["venue_id", "name", "space_id", "business_unit_id", "asset_type_id"],
               parents={"venue_id": "venue_id", "space_id": "space_id",
                        "business_unit_id": "business_unit_id"}),
    EntitySpec("zone", "zones", "zones", ZoneIn,
               ["space_id", "name", "polygons"],
               parents={"space_id": "space_id"},
               json_columns={"polygons"}),
    EntitySpec("sensor", "sensors", "sensors", SensorIn,
               ["asset_id", "video_source_id", "zone_id", "type", "role",
                "conf_threshold", "enabled", "params"],
               parents={"asset_id": "asset_id", "video_source_id": "video_source_id",
                        "zone_id": "zone_id"},
               json_columns={"params"}, bool_columns={"enabled"}),
]
