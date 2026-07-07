# Acceptance Criteria

## Product-Level Acceptance

Strikee Vision is acceptable as a product specification when it defines a generic, local-first Operations Intelligence Platform that can be implemented without hardcoding a venue category or choosing technologies prematurely.

## Core Acceptance Criteria

### Organization and Venue

Accepted when:

- An Organization can contain one or more Venues.
- A Venue can define timezone, operating hours, Spaces, Video Sources, Assets, Sensors, policies, dashboards, and notifications.
- A Venue can contain one or more Business Units for separate operational analytics.
- A single-Venue customer can use the product without unnecessary multi-venue complexity.
- Organization-level governance does not prevent Venue-level autonomy.

### Business Unit Separation

Accepted when:

- A Business Unit can represent a separately tracked business line under the same Organization or Venue.
- Assets can be assigned to Business Units.
- Sessions and Events can inherit Business Unit attribution from Assets or explicit rules.
- Dashboards and analytics can filter by Business Unit independently from Space.
- Shared Spaces such as passages, lobbies, waiting areas, and entrances can be neutral, shared, or attributed by rule.
- Business Unit separation does not require duplicating the Venue or hardcoding a business category.

### Space Modeling

Accepted when:

- A Venue can contain multiple Spaces.
- Spaces can be nested or grouped where useful.
- Spaces can host Video Sources, Assets, and Zones.
- Users can navigate from Organization to Venue to Space to Asset.

### Video Source Management

Accepted when:

- Video Sources can be registered and assigned to Venues and Spaces.
- The product can show source health.
- The product can distinguish active, disabled, offline, degraded, and unknown source conditions.
- Video remains local by default.
- Any cloud video use is explicit and permissioned.

### Asset Configuration

Accepted when:

- Users can create configurable Asset Types.
- Users can create Assets from Asset Types.
- Assets can be placed in Spaces.
- Assets can be linked to Zones or polygons.
- Asset labels can use customer terminology without code changes.
- Dashboards and analytics automatically include configured Assets.

### Sensor Configuration

Accepted when:

- A Sensor is a first-class object with a subject (the Asset it observes), an evidence source (a Video Source), and a spatial scope (a Zone).
- A Sensor's lifecycle home is its subject Asset; it is configured and deleted through that Asset.
- Camera-health sensing is a property of the Video Source, not a Sensor.
- Sensors can define thresholds, schedules, and confidence behavior.
- Sensors can be enabled, disabled, and tested.
- Sensor history remains meaningful after a Sensor is disabled.

### Observation Handling

Accepted when:

- AI and signal outputs are captured as Observations.
- Observations include source, time, scope, value, and confidence.
- Observations do not directly become business truth.
- Low-confidence or stale Observations are handled explicitly.

### State Derivation

Accepted when:

- Assets, Spaces, Sensors, and Video Sources can have current State.
- State is composed of three facets — presence, activity, and health — each with its own value, confidence, and effective time.
- The dashboard shows one derived display label from the facets, with health taking priority (a degraded or offline camera never shows a confident business status).
- State includes effective time, reason, and freshness.
- Unknown is supported as a first-class State.
- Noisy Observations do not cause unstable state flapping.

### Event Generation

Accepted when:

- Events are immutable.
- State transitions can create Events.
- Thresholds can create Events.
- Manual corrections create Events.
- Events include origin, time, subject, scope, and reason.
- Events drive dashboards, analytics, notifications, and Sessions.

### Session Management

Accepted when:

- Sessions can be derived from Events.
- Sessions have start, optional end, status, confidence, and participating Assets.
- Sessions can be detected, confirmed, corrected, voided, and reviewed.
- Corrections preserve original history.
- Not every Event is forced into a Session.

### Dashboard

Accepted when:

- Operators can see current Venue state.
- Managers can see active Sessions, recent Events, and Notifications.
- Owners can see cross-venue or historical performance where applicable.
- Data freshness and health are visible.
- Dashboard labels adapt to configured Assets and Spaces.

### Polygon Editor

Accepted when:

- Users can draw, edit, map, test, and activate polygons.
- Polygons can define Zones, Asset regions, Sensor scopes, and privacy masks.
- The editor warns about configuration issues.
- Polygon changes are auditable.
- Historical Events can reference relevant configuration context.

### Analytics

Accepted when:

- Analytics are derived from Events, Sessions, and Metric Samples (periodic scalar snapshots), never from raw video.
- Scalar metrics such as average, peak, and by-hour occupancy come from Metric Samples.
- Metrics are traceable.
- Reports can filter by Venue, Space, Asset Type, Asset, Event Type, Session Type, State, and time.
- Reports can filter by Business Unit independently from physical Space.
- Data completeness warnings are visible.
- Reports do not require raw video access by default.

### Notifications

Accepted when:

- Notifications are created from Events or persistent State conditions.
- Notification rules define scope, severity, recipient, channel, cooldown, and escalation.
- Notifications can be acknowledged and resolved.
- Notifications link back to Events.
- Notification noise is controlled through cooldown and suppression.

### AI Behavior

Accepted when:

- AI produces Observations.
- Product rules decide State, Events, Sessions, and Notifications.
- Confidence is visible and meaningful.
- Low confidence can produce Unknown or Degraded conditions.
- Identity recognition is not part of default scope.

### Privacy

Accepted when:

- Video stays local by default.
- Privacy masks and observation-disabled zones are supported.
- Evidence access is permissioned.
- Sensitive access is auditable.
- Retention policies are configurable.

### Auditability

Accepted when:

- Configuration changes are traceable.
- Events are immutable.
- Corrections create new records.
- User actions on Events, Sessions, Notifications, and sensitive evidence are recorded.

## Provisional Performance Targets

These numeric targets make "real-time" and "reliable" testable. Each is tagged **provisional — validate after camera sampling** and is tunable once real footage exists.

- **State freshness:** state reflects reality within ~15 s under normal conditions. *(provisional — validate after camera sampling)*
- **Stale → Unknown:** no fresh reading for ~30–60 s flips state to Unknown/Degraded rather than showing stale data. *(provisional — validate after camera sampling)*
- **Occupancy accuracy:** correct occupied-vs-available on high-priority assets ≥ 90% under normal operating conditions. *(provisional — validate after camera sampling)*
- **Session timing:** start/end within ±1–2 min of truth — not billing-grade, human-correctable. *(provisional — validate after camera sampling)*
- **Camera-down visibility:** offline/degraded camera surfaces on the dashboard within ~60 s. *(provisional — validate after camera sampling)*
- **Dashboard load/refresh:** live view usable within ~2–3 s. *(provisional — validate after camera sampling)*

## End-to-End Acceptance Scenarios

### Scenario 1: Configure a New Venue

Given an Admin has a new Venue,  
when they define Spaces, Video Sources, Assets, polygons, and Sensors,  
then the product can generate live States and Events without code changes.

### Scenario 2: Detect and Display Occupancy

Given an Asset has an occupancy Sensor,  
when Observations meet the configured rule threshold,  
then the Asset State changes and an immutable Event is created.

### Scenario 3: Start and End a Session

Given Session rules are configured for an Asset Type,  
when start and end Events occur,  
then a Session is created with duration and status.

### Scenario 4: Handle Low Confidence

Given a Sensor receives low-confidence Observations,  
when confidence remains below threshold,  
then the product should avoid false certainty and may mark the State as Unknown or Degraded.

### Scenario 5: Correct a Session

Given a detected Session has an incorrect end time,  
when a Reviewer corrects the Session,  
then the product creates a correction Event and analytics use corrected truth while preserving the original record.

### Scenario 6: Notify on Operational Exception

Given a Notification Rule exists for a queue threshold,  
when the threshold Event occurs,  
then the product sends a Notification to configured recipients and records acknowledgement.

### Scenario 7: Source Goes Offline

Given a Video Source is active,  
when it stops producing usable input,  
then the product creates a health Event, marks impacted States as Unknown or Degraded, and notifies responsible users.

### Scenario 8: Operate Without Cloud Video

Given cloud upload is disabled,  
when the Venue operates normally,  
then local dashboards, Events, States, Sessions, and core analytics remain available.

## Rejection Criteria

The product direction should be rejected or redesigned if:

- It requires hardcoded gaming, snooker, restaurant, warehouse, or office objects.
- It requires continuous cloud video upload for core operation.
- AI output directly becomes business truth without rules.
- Events can be edited in place.
- Users cannot tell whether data is stale or uncertain.
- Notifications are generated from raw low-confidence observations.
- Analytics cannot be traced back to Events or Sessions.
- Privacy controls are optional afterthoughts.
