# Analytics Specification

## Purpose

Analytics turns immutable Events, Sessions, and Metric Samples into historical insight for owners, managers, and operators.

Analytics draws on three sources: **Events** and **Sessions** provide business facts and spans, while **Metric Samples** provide the scalar/continuous time-series (average occupancy, peak occupancy, occupancy by hour, queue over time). Metric Samples are periodic scalar snapshots taken on each processing tick (roughly every 5–10 seconds), so they add no inference cost. They are high-volume with short retention and are downsampled to hourly/daily aggregates.

Analytics should never depend on raw video as the reporting source. Raw video may provide evidence for review, but business metrics must come from Events, Sessions, and Metric Samples.

## Analytics Principles

- Every metric should be traceable to Events, Sessions, or Metric Samples.
- Scalar/continuous metrics (average occupancy, peak occupancy, occupancy by hour, queue over time) are sourced from periodic Metric Samples; Events and Sessions provide facts and spans.
- Metric Samples have short retention with downsampling to hourly/daily aggregates.
- Analytics never come from raw video.
- Reports should use configured business language.
- Analytics should remain generic across venue categories.
- The product should distinguish measured facts from estimates.
- Confidence and data completeness should be visible where relevant.
- Physical layout and business attribution should be filterable independently.

## Core Metric Categories

### Utilization

Questions answered:

- Which Assets are used most?
- Which Assets are underused?
- What times are busiest?
- How does utilization vary by Business Unit, Space, Asset Type, or Venue?

Possible metrics:

- Utilization percentage.
- Occupied time.
- Available time.
- Idle time.
- Active Session count.
- Average Session duration.
- Peak concurrent Sessions.

### Occupancy and Presence

Questions answered:

- How many people or activities are present in a Space?
- When are spaces busiest?
- How long do areas remain occupied?

Possible metrics:

- Occupancy estimate.
- Presence duration.
- Dwell time.
- Peak occupancy.
- Average occupancy.
- Occupancy by hour.

### Flow and Queue

Questions answered:

- Where do people wait?
- How long do queues or waiting areas persist?
- When do thresholds get exceeded?

Possible metrics:

- Queue estimate over time.
- Threshold breach count.
- Average dwell.
- Longest wait condition.
- Time above threshold.

### Sessions

Questions answered:

- How many activity periods occurred?
- How long did they last?
- How many were corrected?
- Which Business Unit should each Session be attributed to?

Possible metrics:

- Session count.
- Session duration.
- Confirmed Sessions.
- Corrected Sessions.
- Voided Sessions.
- Session confidence distribution.

### Events

Questions answered:

- What happened most often?
- Which operational exceptions repeat?
- Which Events trigger action?

Possible metrics:

- Event count by type.
- Event count by Business Unit.
- Event count by Space.
- Event count by Asset Type.
- Event severity distribution.
- Time to acknowledgement.
- Time to resolution.

### Business Unit Performance

Questions answered:

- How is each business line performing inside the same Venue?
- Which Business Unit has the highest utilization?
- Which Business Unit has the most Sessions or exceptions?
- Which shared Spaces support multiple Business Units?

Possible metrics:

- Sessions by Business Unit.
- Utilization by Business Unit.
- Event count by Business Unit.
- Active Asset count by Business Unit.
- Shared Space activity.
- Business Unit health and data completeness.

### Health and Reliability

Questions answered:

- Are cameras and Sensors reliable?
- Where is data incomplete?
- Which areas require setup improvement?

Possible metrics:

- Video Source uptime.
- Sensor uptime.
- Unknown State duration.
- Degraded State duration.
- Observation freshness.
- Low-confidence Event count.

## Required Analytics Views

### Venue Performance

Shows:

- Utilization.
- Business Unit comparison.
- Session volume.
- Event trends.
- Active and historical health issues.
- Top Spaces by activity.

### Space Performance

Shows:

- Activity by Space.
- Asset state distribution.
- Session timeline.
- Event patterns.
- Health and coverage warnings.

For MVP, Spaces nest one level only, and a Space's roll-up is the simple sum of that Space's assets.

### Asset Performance

Shows:

- Utilization.
- State history.
- Session count and duration.
- Events.
- Confidence and review status.

### Operational Exceptions

Shows:

- Repeated alerts.
- Long dwell.
- Threshold breaches.
- Blocked or unavailable Assets.
- Offline or degraded sources.

### Review Quality

Shows:

- Detected vs confirmed Sessions.
- Correction rate.
- False positive markers.
- Confidence distribution.
- Configuration improvement candidates.

## Filters and Dimensions

Required dimensions:

- Organization.
- Venue.
- Business Unit.
- Space.
- Asset Type.
- Asset.
- Sensor Type.
- Event Type.
- Session Type.
- State.
- Severity.
- Time range.
- Operating hours vs outside hours.
- Confidence band.
- Review status.

## Data Completeness

Analytics must show when data may be incomplete due to:

- Offline Video Source.
- Disabled Sensor.
- Privacy mask.
- Low confidence.
- Unknown State.
- Configuration changes.
- Missing end Event.

Reasoning: A clean chart based on incomplete observation can mislead operators.

## Reporting Behavior

Reports should support:

- Saved views.
- Export of Event and Session summaries.
- Scheduled report delivery where cloud or local messaging permits.
- Role-based access.
- Comparison across time periods.
- Comparison across Venues where enabled.
- Business Unit comparison inside a Venue.

## Anti-Patterns

Avoid:

- Metrics that cannot be traced to Events or Sessions.
- Raw AI counts presented as exact truth.
- Cross-venue comparison without normalizing operating hours.
- Treating physical Spaces as the only analytics boundary.
- Hardcoded gaming business assumptions.
- Staff surveillance metrics by identity.

## Acceptance Notes

Analytics is acceptable when an owner can understand usage, bottlenecks, reliability, and operational exceptions without watching footage or exporting raw data.
