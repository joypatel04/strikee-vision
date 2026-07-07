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

-- ── Runtime tables (M3) ────────────────────────────────────────────────
-- Events are APPEND-ONLY: never updated or deleted. Corrections are new
-- events. No FK to assets, so history survives asset deletion.
CREATE TABLE IF NOT EXISTS events (
    id                TEXT PRIMARY KEY,
    venue_id          TEXT NOT NULL,
    asset_id          TEXT,
    business_unit_id  TEXT,
    type              TEXT NOT NULL,       -- state_change | session_start | session_end
                                           -- | session_confirmed | session_corrected
                                           -- | session_voided | manual
    ts                TEXT NOT NULL,       -- effective time of the fact
    presence          TEXT,
    activity          TEXT,
    health            TEXT,
    label             TEXT,
    prev_label        TEXT,
    confidence        REAL,
    origin            TEXT NOT NULL DEFAULT 'system',   -- system | user
    actor             TEXT,
    reason            TEXT,
    correlation_id    TEXT,                -- e.g. the session id this relates to
    created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_venue_ts ON events(venue_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_asset    ON events(asset_id);
CREATE INDEX IF NOT EXISTS idx_events_corr     ON events(correlation_id);

-- Sessions are MATERIALIZED. A session opens when presence becomes present
-- and closes when it becomes absent (the grace window lives in presence
-- smoothing). One session = one Asset = one Business Unit. Original start/end
-- are preserved on correction.
CREATE TABLE IF NOT EXISTS sessions (
    id                TEXT PRIMARY KEY,
    venue_id          TEXT NOT NULL,
    asset_id          TEXT NOT NULL,
    business_unit_id  TEXT,
    type              TEXT NOT NULL DEFAULT 'usage',
    start_ts          TEXT NOT NULL,
    end_ts            TEXT,
    duration_sec      INTEGER,
    status            TEXT NOT NULL DEFAULT 'detected',  -- detected|confirmed|corrected|voided
    confidence        REAL,
    start_event_id    TEXT,
    end_event_id      TEXT,
    orig_start_ts     TEXT,                -- preserved when corrected
    orig_end_ts       TEXT,
    start_snapshot    TEXT,                -- evidence image path saved at game start
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_venue     ON sessions(venue_id);
CREATE INDEX IF NOT EXISTS idx_sessions_asset_end ON sessions(asset_id, end_ts);

-- ── Metric samples (M4) ────────────────────────────────────────────────
-- Periodic scalar snapshots, one set per asset per tick. High volume, short
-- retention (downsampling to hourly/daily aggregates is a later concern).
-- Long format: one row per (asset, metric) per tick.
CREATE TABLE IF NOT EXISTS metric_samples (
    id                TEXT PRIMARY KEY,
    venue_id          TEXT NOT NULL,
    asset_id          TEXT,
    business_unit_id  TEXT,
    ts                TEXT NOT NULL,
    metric            TEXT NOT NULL,       -- present | persons | confidence | health_ok
    value             REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_samples_venue_ts   ON metric_samples(venue_id, ts);
CREATE INDEX IF NOT EXISTS idx_samples_asset_metric ON metric_samples(asset_id, metric, ts);

-- ── Rules + Notifications (M5) ─────────────────────────────────────────
-- Rules are instances of a fixed template catalog (see app/notify.py). Users
-- tune params + toggle enabled; no free-form logic.
CREATE TABLE IF NOT EXISTS rules (
    id             TEXT PRIMARY KEY,
    venue_id       TEXT NOT NULL,
    name           TEXT NOT NULL,
    template_type  TEXT NOT NULL,        -- label_became | health_became | ...
    enabled        INTEGER NOT NULL DEFAULT 1,
    severity       TEXT NOT NULL DEFAULT 'warning',   -- info | warning | critical
    cooldown_sec   INTEGER NOT NULL DEFAULT 300,
    channel        TEXT NOT NULL DEFAULT 'in_app',    -- in_app | email | sms | webhook
    params         TEXT,                 -- JSON matcher config
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rules_venue ON rules(venue_id);

CREATE TABLE IF NOT EXISTS notifications (
    id                TEXT PRIMARY KEY,
    venue_id          TEXT NOT NULL,
    rule_id           TEXT,
    event_id          TEXT,
    asset_id          TEXT,
    business_unit_id  TEXT,
    severity          TEXT NOT NULL DEFAULT 'warning',
    status            TEXT NOT NULL DEFAULT 'pending',  -- pending|delivered|acknowledged
                                                        -- |resolved|suppressed|failed
    channel           TEXT NOT NULL DEFAULT 'in_app',
    title             TEXT,
    message           TEXT,
    acknowledged_by   TEXT,
    acknowledged_at   TEXT,
    resolved_by       TEXT,
    resolved_at       TEXT,
    reason            TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notifs_venue_status ON notifications(venue_id, status);
CREATE INDEX IF NOT EXISTS idx_notifs_rule_asset   ON notifications(rule_id, asset_id, created_at);
