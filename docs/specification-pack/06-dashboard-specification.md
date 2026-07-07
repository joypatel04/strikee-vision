# Dashboard Specification

## Dashboard Purpose

The dashboard is the operational surface of Strikee Vision. It should let users understand the current state of a Venue quickly, act on exceptions, and inspect the Events and Sessions behind the current view.

The dashboard should be dense, clear, and work-focused. It is not a marketing page and should not rely on decorative visuals.

## Dashboard Principles

- Show current operational truth first.
- Prioritize exceptions over decoration.
- Always reveal data freshness.
- Link every status to Events or evidence.
- Adapt to configured Assets and Spaces.
- Keep video preview permissioned and secondary.
- Avoid industry-specific hardcoding.

## Dashboard Scopes

### Organization Dashboard

Audience: Owners and executives.

Primary questions:

- Which Venues need attention?
- Which Venues are most active?
- Are there source or sensor health problems?
- How are utilization and sessions trending?

Main components:

- Venue status list.
- Cross-venue KPIs.
- Active alerts.
- Health summary.
- Utilization trends.
- Event trend comparison.

### Venue Dashboard

Audience: Venue managers and operators.

Primary questions:

- What is happening now?
- Which Spaces or Assets need action?
- Which Sessions are active?
- What Events occurred recently?
- Are cameras and Sensors healthy?
- How is activity split by Business Unit?

Main components:

- Space map or list.
- Business Unit filter or segmented view.
- Asset state grid.
- Active Sessions.
- Recent Events.
- Notifications.
- Source and Sensor health.
- Time filter and Space filter.

### Space Dashboard

Audience: Managers, operators, installers.

Primary questions:

- What is happening in this physical area?
- Which Assets are occupied, idle, waiting, blocked, or unknown?
- Which Video Sources cover this Space?
- Which Business Units use this Space?

Main components:

- Space layout view.
- Asset cards or rows.
- Zone overlays where permitted.
- Space-level Events.
- Active Sensors.
- Health warnings.

### Asset Detail View

Audience: Managers, reviewers, installers.

Primary questions:

- What is the current State?
- Why does the product think that?
- What happened recently?
- Which Sessions involved this Asset?

Main components:

- Current State.
- Confidence and freshness.
- Active Sensor list.
- Event timeline.
- Session history.
- Evidence references where permitted.
- Configuration summary.

## Dashboard Object Behavior

### State Display

An Asset's State is composed of three facets — presence (absent, present, or unknown), activity (active, inactive, or unknown), and health (ok, degraded, or offline). The dashboard does not show these facets raw; it shows one derived display label from them, with health taking priority. A degraded or offline camera never shows a confident business status. Example labels: Active (In Use), Occupied – Idle, Available, and Unknown/Degraded.

Each state display should show:

- State label (the single derived display label).
- Effective time.
- Freshness.
- Confidence where applicable.
- Reason or last Event.
- Health warning where applicable.

States should never appear as certain when the system lacks evidence. Unknown is a valid and important state.

### Event Feed

Event feed should support:

- Time ordering.
- Severity.
- Event type.
- Scope.
- Subject.
- Origin.
- Filter by Space, Asset, Sensor, Event Type, severity, and time.
- Link to detail.

### Active Session List

Active Sessions should show:

- Session type.
- Asset or Assets involved.
- Start time.
- Duration.
- Confidence.
- Status.
- Open review action when applicable.

### Health Summary

Health should cover:

- Video Source health.
- Sensor health.
- Observation freshness.
- State freshness.
- Last successful observation.
- Impacted Assets and Spaces.

## Dashboard Roles

### Owner View

Default emphasis:

- Venue comparison.
- Trends.
- Exceptions.
- Business KPIs.

Limited emphasis:

- Raw video.
- Detailed Sensor tuning.

### Manager View

Default emphasis:

- Live operation.
- Notifications.
- Review queue.
- Session status.
- Health.

### Staff View

Default emphasis:

- Current actions.
- Availability.
- Alerts.

Limited emphasis:

- Configuration.
- Analytics.
- Evidence playback unless permitted.

### Admin View

Default emphasis:

- Configuration.
- Coverage.
- Health.
- Sensor testing.

## Required Dashboard Filters

- Organization.
- Venue.
- Space.
- Asset Type.
- Asset.
- Sensor Type.
- State.
- Event Type.
- Severity.
- Time range.
- Confidence.
- Review status.
- Business Unit.

## Required Dashboard Actions

- Acknowledge Notification.
- Resolve Notification.
- Open Event detail.
- Open Session detail.
- Confirm Session.
- Correct Session.
- Mark Event as reviewed.
- Open Asset detail.
- Open Space detail.
- Filter by Business Unit.
- Open health issue.
- Open configuration where permitted.

## Dashboard Anti-Patterns

Avoid:

- Showing raw AI detections as final truth.
- Hiding stale data.
- Requiring video playback to understand every Event.
- Hardcoding gaming-specific cards.
- Showing too many low-value alerts.
- Ranking staff by identity or productivity.
- Presenting confidence as accuracy.

## Dashboard Acceptance Notes

The dashboard is acceptable when a Venue Manager can open it and answer, within seconds:

- Which areas need attention?
- Which Assets are currently active or unavailable?
- What changed recently?
- Are sensors and cameras healthy?
- Which notifications need action?
