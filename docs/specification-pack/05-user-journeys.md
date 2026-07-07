# User Journeys

## Primary Personas

### Owner or Executive

Goals:

- Understand venue performance.
- Compare locations.
- Reduce manual oversight.
- Improve utilization and operating visibility.
- Avoid operational blind spots.

Needs:

- High-level dashboards.
- Trusted analytics.
- Exceptions and trends.
- Minimal setup friction.

### Venue Manager

Goals:

- Run daily operations.
- See what needs attention now.
- Confirm or correct sessions.
- Ensure cameras and sensors are working.

Needs:

- Live dashboard.
- Notifications.
- Review queue.
- Space and asset views.

### Staff Operator

Goals:

- Respond to operational issues.
- Know which assets are available, occupied, waiting, or blocked.
- Acknowledge alerts.

Needs:

- Simple live view.
- Clear notification action.
- Minimal configuration access.

### Admin or Installer

Goals:

- Configure Venues, Spaces, Video Sources, Assets, Sensors, and polygons.
- Validate detection quality.
- Tune thresholds.

Needs:

- Guided setup.
- Polygon editor.
- Test mode.
- Health and calibration feedback.

### Reviewer or Auditor

Goals:

- Review Events and Sessions.
- Confirm accuracy.
- Correct history without destroying audit trail.

Needs:

- Event timeline.
- Evidence access.
- Correction workflow.
- Audit log.

## Journey 1: First Venue Setup

1. Admin creates an Organization or opens an existing Organization.
2. Admin creates a Venue with name, timezone, operating hours, and privacy defaults.
3. Admin creates Spaces that match the physical layout.
4. Admin registers Video Sources and maps them to Spaces.
5. Admin creates Asset Types or selects templates.
6. Admin creates Assets and places them in Spaces.
7. Admin draws zones or polygons for Assets.
8. Admin enables Sensors for Assets or Zones.
9. Admin runs test mode.
10. Product shows confidence, coverage, and warnings.
11. Admin adjusts polygons and thresholds.
12. Admin activates the Venue.

Success criteria:

- The Venue can generate at least one useful Event from configured Assets.
- The dashboard shows live Asset states.
- Health status is visible.

## Journey 2: Live Operations

1. Venue Manager opens the live dashboard.
2. Product shows Spaces, Assets, current States, active Sessions, and recent Events.
3. A configured condition occurs.
4. The product generates Observations.
5. State changes when rules are satisfied.
6. An Event is created.
7. Dashboard updates.
8. If configured, a Notification is delivered.
9. Staff acknowledges or resolves the issue.
10. Acknowledgement is recorded as an Event.

Success criteria:

- Operators can understand what happened without watching continuous video.
- Notifications link back to the related Event.
- The system remains useful if cloud sync is disabled.

## Journey 3: Session Review and Correction

1. Reviewer opens Session timeline.
2. Product shows detected Sessions by Venue, Space, Asset, and time.
3. Reviewer selects a Session.
4. Product shows start Event, end Event, confidence, and allowed evidence.
5. Reviewer confirms, corrects, or voids the Session.
6. Product creates a correction Event.
7. Analytics use the corrected Session status.

Success criteria:

- Original Events remain intact.
- Corrections are auditable.
- Dashboard and analytics reflect corrected business truth.

## Journey 4: Camera or Sensor Health Failure

1. Video Source stops producing usable input or confidence drops below threshold.
2. Source health State changes to Degraded or Offline.
3. Event is generated.
4. Notification is sent to responsible users.
5. Dashboard marks affected Assets, Sensors, and Spaces as Unknown or Degraded.
6. User resolves issue or disables affected Sensors.
7. Recovery Event is generated when health returns.

Success criteria:

- The product does not silently show stale or false states.
- Impacted operational areas are visible.

## Journey 5: Add a New Asset Type

1. Admin opens Asset Type management.
2. Admin creates a generic Asset Type with name, description, allowed states, default Sensors, and optional Session rules.
3. Admin creates one or more Assets using the Asset Type.
4. Admin maps each Asset to Space and polygon.
5. Admin tests detection.
6. Product begins generating Events for the new Assets.

Success criteria:

- No code or technology change is required.
- Dashboards and analytics include the new Asset Type automatically.

## Journey 6: Configure a Queue or Waiting Area

1. Admin creates an Asset Type such as "Queue Area" or "Waiting Area."
2. Admin creates an Asset in the relevant Space.
3. Admin draws a polygon around the area.
4. Admin enables count, dwell, or threshold Sensors.
5. Admin configures Events such as "threshold exceeded" or "dwell too long."
6. Admin configures Notifications.
7. Operators receive alerts when the condition occurs.

Success criteria:

- The same workflow can be used for a cafe queue, reception waiting area, warehouse loading queue, or office lobby.

## Journey 7: Privacy-Conscious Operation

1. Admin marks sensitive areas in a Space.
2. Admin applies privacy masks or disables observation.
3. Admin restricts evidence access to specific roles.
4. Product logs access to sensitive evidence.
5. Analytics use Events without exposing unnecessary video.

Success criteria:

- Operational insight is available without broad video access.
- Users can verify what is observed and what is excluded.

## Journey 8: Multi-Venue Performance Review

1. Owner opens organization-level analytics.
2. Product shows venue comparison based on Events and Sessions.
3. Owner filters by date, Venue, Space type, Asset Type, or Event Type.
4. Owner identifies underused Assets, high-wait periods, or health issues.
5. Owner exports or shares a report if permitted.

Success criteria:

- Cross-venue insight uses consistent generic entities.
- Venue-specific terminology remains configurable.
