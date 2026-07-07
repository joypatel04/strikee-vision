-- Strikee Vision Local Core — configuration schema (M1)
-- Config entities only. Runtime tables (observations, states, events,
-- sessions, metric_samples, notifications) are added in later milestones.
--
-- Reflects the reconciled domain model: Space and Business Unit are parallel
-- children of Venue; a Sensor is owned by its Asset and references one Video
-- Source (evidence) and one Zone (scope); a Zone owns one or more polygons.

CREATE TABLE IF NOT EXISTS organizations (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS venues (
    id               TEXT PRIMARY KEY,
    organization_id  TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    timezone         TEXT NOT NULL DEFAULT 'UTC',
    operating_hours  TEXT,                       -- JSON
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

-- Business Unit: analytics attribution, a parallel child of Venue (not stacked
-- above Space). Assets carry the attribution.
CREATE TABLE IF NOT EXISTS business_units (
    id          TEXT PRIMARY KEY,
    venue_id    TEXT NOT NULL REFERENCES venues(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    kind        TEXT,                            -- e.g. snooker, gaming, shared
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Space: physical layout, a parallel child of Venue. One-level nesting for MVP.
CREATE TABLE IF NOT EXISTS spaces (
    id               TEXT PRIMARY KEY,
    venue_id         TEXT NOT NULL REFERENCES venues(id) ON DELETE CASCADE,
    parent_space_id  TEXT REFERENCES spaces(id) ON DELETE SET NULL,
    name             TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS video_sources (
    id          TEXT PRIMARY KEY,
    venue_id    TEXT NOT NULL REFERENCES venues(id) ON DELETE CASCADE,
    space_id    TEXT REFERENCES spaces(id) ON DELETE SET NULL,
    name        TEXT NOT NULL,
    uri         TEXT,                            -- rtsp url / file / index
    status      TEXT NOT NULL DEFAULT 'registered',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS asset_types (
    id             TEXT PRIMARY KEY,
    venue_id       TEXT NOT NULL REFERENCES venues(id) ON DELETE CASCADE,
    name           TEXT NOT NULL,
    min_start_sec  INTEGER NOT NULL DEFAULT 14,  -- session open threshold
    min_clear_sec  INTEGER NOT NULL DEFAULT 21,  -- session close grace window
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
    id                TEXT PRIMARY KEY,
    venue_id          TEXT NOT NULL REFERENCES venues(id) ON DELETE CASCADE,
    space_id          TEXT REFERENCES spaces(id) ON DELETE SET NULL,
    business_unit_id  TEXT REFERENCES business_units(id) ON DELETE SET NULL,
    asset_type_id     TEXT REFERENCES asset_types(id) ON DELETE SET NULL,
    name              TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

-- Zone: the only linkable spatial object; owns one or more polygons.
CREATE TABLE IF NOT EXISTS zones (
    id          TEXT PRIMARY KEY,
    space_id    TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    polygons    TEXT,                            -- JSON: [[[x,y],...], ...]
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Sensor: first-class object owned by its Asset, referencing one Video Source
-- (evidence) and one Zone (scope). role = primary | supporting.
CREATE TABLE IF NOT EXISTS sensors (
    id               TEXT PRIMARY KEY,
    asset_id         TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    video_source_id  TEXT REFERENCES video_sources(id) ON DELETE SET NULL,
    zone_id          TEXT REFERENCES zones(id) ON DELETE SET NULL,
    type             TEXT NOT NULL DEFAULT 'occupancy',
    role             TEXT NOT NULL DEFAULT 'primary',
    conf_threshold   REAL NOT NULL DEFAULT 0.35,
    enabled          INTEGER NOT NULL DEFAULT 1,
    params           TEXT,                       -- JSON
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_venues_org       ON venues(organization_id);
CREATE INDEX IF NOT EXISTS idx_bu_venue          ON business_units(venue_id);
CREATE INDEX IF NOT EXISTS idx_spaces_venue      ON spaces(venue_id);
CREATE INDEX IF NOT EXISTS idx_sources_venue     ON video_sources(venue_id);
CREATE INDEX IF NOT EXISTS idx_asset_types_venue ON asset_types(venue_id);
CREATE INDEX IF NOT EXISTS idx_assets_venue      ON assets(venue_id);
CREATE INDEX IF NOT EXISTS idx_zones_space       ON zones(space_id);
CREATE INDEX IF NOT EXISTS idx_sensors_asset     ON sensors(asset_id);
