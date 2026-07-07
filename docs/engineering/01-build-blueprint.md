# Build Blueprint

Status: Draft for engineering
Scope: Implementation architecture and tech choices. This is the technology layer the specification pack deliberately left out. Where this document and the specification pack disagree on product behavior, the specification pack and the [Decision Log](../specification-pack/13-decision-log.md) win.

## 1. What we are building

Two deployables:

1. **Local Core (Windows)** — the product. Runs entirely on-site: pulls camera feeds, runs YOLO on a periodic tick, derives state, writes immutable events, materializes sessions, samples metrics, evaluates rule templates, dispatches notifications, and serves the **local dashboard**. Fully useful with no internet.
2. **Remote Monitor (web, later)** — a minimal, read-only web app to watch one or more venues from anywhere. The Local Core pushes state/event/session/metric summaries to it best-effort. No video ever leaves the venue. Optional; the product works without it.

Governing constraints (from [deployment decisions](../specification-pack/17-gaps-and-open-questions.md) G04): local Windows, on-device AI, **periodic 5–10s processing tick** (not per-frame), tight performance budget, dashboard-first, no video stored by default.

## 2. Architecture at a glance

```
                         LOCAL CORE (Windows, on-site)
  ┌───────────────────────────────────────────────────────────────────┐
  │  Cameras (RTSP) ─► Capture ─► Perception(YOLO) ─► Observation       │
  │                                    every 5–10s tick                 │
  │                                         │                           │
  │                                         ▼                           │
  │   Rule templates ──►  State Engine (presence/activity/health facets,│
  │                        smoothing, primary/supporting fusion)        │
  │                                         │                           │
  │              ┌──────────────────────────┼───────────────┐          │
  │              ▼                           ▼               ▼          │
  │        Event Store               Metric Sampler     Health Monitor  │
  │        (append-only)             (scalar/tick)                      │
  │              │                           │                          │
  │        ┌─────┼─────────┐                 │                          │
  │        ▼     ▼         ▼                 │                          │
  │   Sessions  Notifier  Analytics ◄────────┘                         │
  │   (materialized) (tiered)                                           │
  │              │                                                      │
  │        SQLite (WAL)  ◄── Config Store, Audit                        │
  │              │                                                      │
  │        FastAPI  ──  REST + WebSocket  ──► Local Dashboard (browser) │
  │              │                                                      │
  │        Remote Sync (best-effort, queued) ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┐    │
  └───────────────────────────────────────────────────────────────┼────┘
                                                                   ▼
                                          REMOTE MONITOR (cloud, read-only, later)
                                          state/event/session/metric summaries only
```

## 3. Tech stack (recommended)

| Layer | Choice | Why |
|---|---|---|
| Language (core) | **Python 3.11+** | The perception layer (Ultralytics/OpenCV/Torch) is Python and already proven in the spike. One language for AI + business logic = no IPC friction. |
| Perception | **Ultralytics YOLO** (yolo11n → s/m), OpenCV | Validated in `spike/perception`. Auto-uses GPU if present. |
| App framework | **FastAPI + Uvicorn** | Async, serves REST + WebSocket for the live dashboard, tiny footprint. |
| Scheduling | **asyncio tick loop** (APScheduler only if needed) | The 5–10s tick is a simple periodic coroutine. |
| Storage | **SQLite (WAL mode)** | Local-first, zero-admin, embedded, fast enough for this event volume. Handles events, sessions, metric samples, config, audit. |
| Validation/models | **Pydantic v2** | Typed domain models, request/response schemas. |
| Local dashboard + remote monitor | **React + Vite + TypeScript + Tailwind**, charts via **uPlot/Recharts** | One frontend codebase serves both the local dashboard and (a subset as) the remote monitor. WebSocket for live updates. |
| Windows packaging | **Tray app**: bundled Python (PyInstaller) + FastAPI serving the built SPA on `localhost`, opened in the default browser or **pywebview** shell | Simple, no Electron weight. Runs as a startup/service. |
| Remote store (optional, later) | **Supabase** (Postgres + auth + realtime) | Already connected to this workspace; the Local Core pushes summaries, the Remote Monitor is a thin client. Self-hosting is the alternative if we want zero third-party. **← decision to confirm when we build the monitor.** |

Rationale summary: Python core (matches the AI), SQLite local store (matches local-first), one React frontend reused for local + remote (matches "minimal web app"), tray-app packaging (matches "runs locally on Windows").

## 4. Local Core components

Each is a module with a narrow responsibility. Data flows one direction: observations never mutate business truth directly.

1. **Capture** — opens RTSP/file/webcam per Video Source; buffer-minimized recent-frame grab; marks source offline/recovered (feeds Health). Reuses the spike's approach.
2. **Perception** — runs YOLO person detection on the sampled frame; returns detections + confidence. One inference pass per camera per tick.
3. **Observation** — normalizes detections into Observations (person-in-Zone via feet/ground-point, confidence, timestamp, source, zone). Raw, never business truth. Optionally persisted short-term for audit.
4. **State Engine** — the heart. Per Asset, combines its sensors' observations into the **three facets** (presence/activity/health) with smoothing (min consecutive, hysteresis) and **primary/supporting fusion** (primary decides; supporting overrides an *empty* presence when confidently occupied). Emits state-change candidates.
5. **Rule Engine** — the fixed **template catalog** (occupancy, activity, session, threshold, health, notification), each with defaults + ON/OFF. Evaluates cheaply each tick. No free-form logic.
6. **Event Store** — append-only, immutable events with origin, subject, scope, reason, confidence, evidence ref. Corrections are new events. The source of business truth.
7. **Session Engine** — materialized sessions; open after min-start duration, close after min-clear (grace window); no auto-reopen; single Asset / single Business Unit; correction/merge as append-only events.
8. **Metric Sampler** — writes one scalar snapshot per sensor per tick (count, confidences, health) to the metric-samples table. Short retention + downsampling. Zero extra inference.
9. **Health Monitor** — camera + sensor freshness/uptime; emits health events; drives the health facet.
10. **Notifier** — tiered delivery: in-app/on-screen always; network channels queued + retried with delivery-degraded banner; every Critical rule needs a local channel.
11. **Config Store** — Org/Venue/BU/Space/Video Source/Asset/Zone/Sensor/Rule/Policy; audited changes; the polygon/zone definitions.
12. **API + WebSocket** — REST for config/review/analytics; WebSocket pushes live state/events to the dashboard.
13. **Remote Sync** — best-effort push of summaries to the Remote Monitor; queued when offline; never blocks local operation.

## 5. Storage model (SQLite sketch)

Tables map directly to the reconciled domain model. Illustrative, not final DDL:

```
organizations, venues, business_units, spaces
video_sources        (health status, schedule, privacy masks)
asset_types          (allowed labels, default sensors, min_start_sec, min_clear_sec)
assets               (space_id, business_unit_id, asset_type_id)
zones                (space_id, polygons JSON)          -- owns 1+ polygons
sensors              (asset_id, video_source_id, zone_id, type, role[primary|supporting],
                      conf_threshold, schedule, enabled, params JSON)
observations         (sensor_id, ts, value, confidence, evidence_ref)   -- short retention
states               (asset_id, presence, activity, health, +conf/effective_time each)  -- current + history
events               (APPEND ONLY: type, subject, scope, ts, origin, reason, confidence,
                      evidence_ref, keyframe_ref, correlation_id, payload JSON)
sessions             (asset_id, business_unit_id, type, start_ts, end_ts, duration,
                      status[detected|confirmed|corrected|voided], confidence)
metric_samples       (sensor_id/asset_id, ts, metric, value)   -- high volume, downsampled
rules                (scope, template_type, enabled, params JSON)
notifications        (rule_id, event_id, severity, status, channel, delivery attempts)
policies, users, roles, permissions, audit_log
evidence             (ref, availability[available|expired|masked], keyframe path)
```

Retention: events + keyframes long; observations + full clips short; metric samples short then rolled to hourly/daily aggregates.

## 6. The tick loop (pseudocode)

```python
async def tick(venue):
    for source in venue.active_video_sources:
        frame, ok = capture.grab_recent(source)
        health.update(source, ok)
        if not ok:
            continue
        detections = perception.detect_persons(frame)          # YOLO, 1 pass
        for sensor in source.sensors:                          # sensors scoped to zones on this source
            obs = observation.build(sensor, detections)        # person-in-zone
            state_engine.feed(sensor.asset, sensor, obs)       # updates facets w/ fusion+smoothing
            metric_sampler.record(sensor, obs)                 # scalar snapshot

    for asset in venue.assets:
        change = state_engine.settle(asset)                    # apply hysteresis, derive label
        if change:
            evt = event_store.append(change)                   # immutable
            session_engine.on_event(asset, evt)                # open/close materialized session
            notifier.evaluate(evt)                             # rule templates -> tiered notify

    remote_sync.enqueue(venue.snapshot())                      # best-effort
# scheduled every INTERVAL (5–10s) per venue
```

## 7. Remote Monitor (minimal, later)

- **Purpose:** watch live status, active sessions, recent events, and camera health across venues from anywhere. Read-only. No config, no video, no review actions in v1.
- **Data path:** Local Core → Remote Sync → cloud store (Supabase Postgres recommended) → Remote Monitor web app (same React codebase, monitor-only routes).
- **Offline behavior:** if the venue's internet drops, the monitor shows "last synced N min ago"; the Local Core keeps working and queues updates.
- **Auth:** per-organization; a viewer sees only their venues (Venue-scoped, matching G14).
- Built after the Local Core MVP is stable.

## 8. Build order (milestones)

Maps to the product roadmap (Phase 1–3) with the perception spike already done.

- **M0 — Spike (done):** YOLO → zone → occupancy → session validated (`spike/perception`).
- **M1 — Skeleton:** repo, SQLite schema, config CRUD for Org→Venue→Space→Video Source→Asset→Zone→Sensor, FastAPI up, static dashboard shell.
- **M2 — Live pipeline:** promote the spike into Capture/Perception/Observation/State Engine (facets + fusion + smoothing); live Asset grid on the dashboard via WebSocket; source health.
- **M3 — Events + Sessions:** append-only event store; materialized sessions (grace window); event feed + active sessions on dashboard; review/correct/void.
- **M4 — Metric Samples + Analytics:** sampler + downsampling; utilization / occupancy / session analytics by Business Unit; data-completeness warnings.
- **M5 — Rules + Notifications:** template catalog with defaults+ON/OFF; tiered notifier; review queue.
- **M6 — Windows packaging:** tray app, autostart, first-run setup wizard, polygon editor in-app.
- **M7 — Remote Monitor:** sync push + minimal read-only web app.

Field-test checkpoint: after **M2**, take it to the club and run the live pipeline for hours (the spike already does a slice of this) to confirm detection quality before investing in M3+.

## 9. Proposed repo structure

```
/local-core/           # Python: FastAPI app, engine modules, SQLite, tests
    /app/
        capture/  perception/  observation/  state/  rules/
        events/  sessions/  metrics/  health/  notify/  config/  sync/
        api/  db/  main.py
    /tests/
    pyproject.toml
/web/                   # React + Vite + TS: dashboard (local) + monitor (remote) routes
/spike/perception/      # existing validated spike (throwaway reference)
/docs/
    /specification-pack/   # product spec (tech-free)
    /engineering/          # this blueprint + future eng docs
```

## 10. Open technical decisions

- **D-T1 Remote store:** Supabase (fast, already connected) vs self-hosted Postgres/API (no third party). Recommend Supabase for the monitor; confirm at M7.
- **D-T2 Dashboard shell:** default browser vs pywebview window vs Tauri. Recommend pywebview (feels like an app, tiny). Confirm at M6.
- **D-T3 Model tier + hardware:** yolo11n on CPU vs s/m with GPU — decided by the field test (accuracy vs the target Windows box's compute).
- **D-T4 Activity facet method:** presence is straightforward (person-in-zone); "activity" (are they actually playing) needs a method — motion between ticks, pose, or table-region change. Prototype after M2 on real footage.
- **D-T5 Multi-venue on one box vs one box per venue:** affects the tick scheduler and sync. Assume one box per venue for MVP.
```
