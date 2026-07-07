# Functional Specification

## Scope

This document defines what Strikee Vision should do from a product behavior perspective. It intentionally avoids implementation architecture, technology selection, and infrastructure decisions.

## Product Modules

### 1. Organization Management

Purpose: Manage the customer account, users, roles, and organization-level policies.

Required capabilities:

- Create and manage Organization profile.
- Manage users.
- Assign roles and permissions.
- Define default privacy and retention policies.
- View organization-level activity and audit history.
- Enable or disable optional cloud features.

Reasoning: Multi-venue customers need central governance, but single-venue customers should not face unnecessary setup burden.

#### Roles and Permissions (MVP)

For MVP, access is scoped by Venue using a fixed role catalog:

| Role | Permissions |
| --- | --- |
| Admin | Configure |
| Reviewer | Review + correct |
| Manager | View + acknowledge + correct |
| Staff | View + acknowledge |
| Owner | View + analytics |

Business-Unit-scoped permissions are planned/post-MVP. Every Asset, Session, and Event already carries Business Unit attribution, so filtering access by Business Unit can be added later without rework.

### 2. Venue Management

Purpose: Model each real-world location.

Required capabilities:

- Create and edit Venues.
- Define timezone and operating hours.
- Configure venue-level privacy settings.
- Configure venue-level notification defaults.
- Configure Business Units or reporting units operating inside the Venue.
- View venue health.
- View all Spaces, Video Sources, Assets, Sensors, and Events in the Venue.

### 2A. Business Unit Management

Purpose: Separate analytics and operational reporting for businesses or departments that operate under the same Organization or Venue.

Required capabilities:

- Create and edit Business Units.
- Assign Business Units to one or more Venues.
- Assign Assets to Business Units.
- Assign default Business Unit attribution to Spaces where useful.
- Support shared Spaces that are not exclusively owned by one Business Unit.
- Filter dashboards, Sessions, Events, and analytics by Business Unit.
- Allow Events and Sessions to inherit Business Unit from their participating Assets unless overridden by explicit rules.

Reasoning: A snooker club and gaming lounge may share a brand, location, cameras, lobby, staff, or entrance while still requiring separate operational analytics.

### 3. Space Management

Purpose: Model the physical layout of a Venue.

Required capabilities:

- Create Spaces and nested Spaces.
- Assign Video Sources to Spaces.
- Assign Assets to Spaces.
- Define zones and polygons.
- Mark sensitive areas.
- View Space health and activity.

Reasoning: Physical operations are spatial. Space configuration lets the product stay generic while still matching real-world layout.

Nesting constraints (MVP):

- Nesting is limited to **one level** for MVP; Venues have flat Spaces.
- Analytics roll-up for a Space is a simple sum of that Space's assets.
- Deeper nesting (e.g., multi-floor) is deferred until a real venue needs it.

### 4. Video Source Management

Purpose: Register and monitor visual inputs.

Required capabilities:

- Add Video Sources.
- Name and describe Video Sources.
- Assign Video Sources to Venues and Spaces.
- Configure operating schedule.
- Set privacy masks.
- View health status.
- View latest frame preview where permitted.
- Mark feed as active, disabled, offline, or degraded.

Product constraints:

- Video should stay local by default.
- Users must understand whether video is local-only or cloud-enabled.
- The product should not require replacing existing CCTV systems.

### 5. Asset Management

Purpose: Define the business-relevant objects, resources, zones, or areas the Venue cares about.

Required capabilities:

- Create Asset Types.
- Create Assets.
- Assign Assets to Venue and Space.
- Assign Assets to Business Unit where analytics separation is required.
- Attach Assets to zones or polygons.
- Configure expected states.
- Configure display name, identifier, and optional grouping.
- Enable or disable Sensors.
- View current state and history.

Examples of Assets:

- Table.
- Station.
- Counter.
- Queue area.
- Machine.
- Shelf.
- Entrance.
- Bay.
- Desk group.
- Waiting area.

These are examples only. They must not be hardcoded product concepts.

### 6. Sensor Configuration

Purpose: Define what the product should observe for each Asset, Space, Zone, or Video Source.

Required capabilities:

- Add Sensor from supported sensor types.
- Configure Sensor scope.
- Configure confidence thresholds.
- Configure dwell thresholds.
- Configure operating schedule.
- Configure event generation rules.
- Test Sensor behavior against current or recent video.
- Disable Sensor without deleting historical Events.

Supported generic Sensor types for early product:

- Presence.
- Occupancy.
- Activity.
- Inactivity.
- Count.
- Queue estimate.
- Dwell.
- Transition.
- Obstruction.
- Source health.

Rejected for early default scope:

- Person identity.
- Face recognition.
- Emotion recognition.
- Demographic classification.

Reasoning: These add privacy risk and are not required for core operational value.

### 7. Observation Handling

Purpose: Capture AI or signal outputs before business decisions are made.

Required capabilities:

- Store or reference Observations according to retention policy.
- Include confidence and source.
- Link Observations to Video Source, Sensor, Zone, and time.
- Mark Observations as usable, low confidence, suppressed, or expired.
- Provide enough evidence for later audit where permitted.

### 8. State Derivation

Purpose: Convert Observations and rules into current operational State.

Required capabilities:

- Maintain current State for Assets, Sensors, Spaces, and Video Sources.
- Track State effective time.
- Track confidence and reason.
- Avoid noisy state changes through smoothing and thresholds.
- Mark State as Unknown when evidence is insufficient.
- Show State history.

Reasoning: Dashboards need stable operational truth, not raw frame-by-frame AI output.

### 9. Event Generation

Purpose: Record immutable business facts.

Required capabilities:

- Generate Events from State transitions.
- Generate Events from threshold crossings.
- Generate Events from manual actions.
- Generate Events from health changes.
- Generate Events from session lifecycle actions.
- Support correction Events.
- Link Events to evidence and configuration context.
- Prevent direct editing of Events.

### 10. Session Management

Purpose: Group Events into meaningful periods of activity.

Required capabilities:

- Define Session Types.
- Configure start and end rules.
- Configure Business Unit attribution rules.
- Detect Sessions automatically.
- Allow manual confirmation.
- Allow manual correction.
- Allow voiding through immutable correction Events.
- View Session timeline.
- Export or report Session summaries.

Session behavior:

- Sessions are materialized records built from Events (not recomputed on each read).
- Each Asset Type must define a **minimum start duration** and a **minimum clear duration** (grace window).
- A Session opens after presence or activity holds for the minimum start duration.
- A Session closes only after activity clears for the minimum clear duration; a straggler reading within the grace window keeps the Session open.
- After a Session closes, late activity does not auto-reopen it — genuine new activity starts a **new** Session.
- To combine Sessions that should be one, a human applies a merge via a correction Event; automatic reopening is never done.
- Corrections (fix start or end, void, merge) are append-only Events; original Sessions are preserved.

Session examples:

- Asset usage interval.
- Queue wait interval.
- Service interval.
- Loading interval.
- Room occupancy interval.

### 11. Dashboard

Purpose: Give operators and managers a live operational view.

Required capabilities:

- Show current state by Venue, Space, and Asset.
- Highlight active, waiting, blocked, offline, and unknown states.
- Show recent Events.
- Show active Sessions.
- Show notifications requiring action.
- Provide filtering by Space, Asset Type, state, severity, and time.
- Provide role-appropriate views.

### 12. Analytics

Purpose: Turn Events and Sessions into historical insight.

Required capabilities:

- Utilization over time.
- Occupancy over time.
- Session counts and duration.
- Business Unit-level activity and utilization.
- Queue or dwell patterns.
- Asset availability.
- State distribution.
- Event frequency.
- Notification performance.
- Source and sensor health trends.

Analytics must be generated from Events and Sessions rather than raw video.

### 13. Notification

Purpose: Alert users when operational Events or conditions require attention.

Required capabilities:

- Configure notification rules.
- Choose recipients and channels.
- Define severity.
- Define cooldowns and escalation.
- Acknowledge notifications.
- Resolve notifications.
- Link notifications to Events.
- Show delivery and acknowledgement status.

### 14. Review and Correction

Purpose: Let users improve trust by reviewing and correcting detected facts.

Required capabilities:

- Review Events and Sessions.
- View allowed evidence.
- Confirm detected facts.
- Correct start or end times.
- Mark false positives.
- Add notes.
- Create correction Events.
- Preserve original Events.

### 15. Privacy and Governance

Purpose: Protect sensitive video-derived data.

Required capabilities:

- Configure video retention.
- Configure evidence retention.
- Configure privacy masks.
- Restrict video preview access.
- Log sensitive access.
- Export audit history.
- Disable observation in sensitive zones.

### 16. Health Monitoring

Purpose: Ensure the product does not silently fail.

Required capabilities:

- Monitor Video Source health.
- Monitor Sensor health.
- Monitor observation freshness.
- Monitor state freshness.
- Show degraded confidence.
- Notify when important sources fail.

## Functional Product Rules

- Observations do not directly create business decisions.
- State changes should be explainable.
- Events are immutable.
- Sessions are derived from Events.
- Notifications reference Events or persistent conditions.
- Manual corrections create new Events.
- Configuration changes must be auditable.
- Video export or cloud upload must be explicit and permissioned.

## Out of Scope for Product V1

- Full custom workflow builder.
- Facial recognition.
- Payment settlement.
- Deep ERP integration.
- Staff identity analytics.
- Voice or audio analytics.
- Predictive demand forecasting beyond basic trends.
- Industry-specific hardcoded dashboards.

## Product Risks

### Setup Complexity

Risk: Too much configuration can block adoption.

Product response: Provide templates, guided setup, test mode, and sensible defaults.

### AI Reliability

Risk: Poor camera angles or lighting can reduce confidence.

Product response: Show confidence, health, calibration warnings, and Unknown state rather than pretending certainty.

### Privacy Concerns

Risk: Operators, staff, or customers may perceive the product as surveillance.

Product response: Focus language on operations, minimize identity features, keep video local, and expose privacy controls.

### Generic Product Drift

Risk: Early customer requests may push the product into hardcoded vertical behavior.

Product response: Accept use-case-specific templates but keep the underlying model generic.
