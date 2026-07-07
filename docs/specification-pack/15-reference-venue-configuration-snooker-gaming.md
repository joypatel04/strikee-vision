# Reference Venue Configuration: Snooker and Gaming

Status: Draft reference configuration  
Purpose: Validate that the generic Strikee Vision product model covers a real mixed-use venue without hardcoding the product for snooker or gaming.

## Venue Summary

The reference Venue contains two business operations under the same name:

- A larger snooker club area.
- A smaller gaming lounge area.
- A connected passage or lobby between them.

Analytics should be tracked separately for the snooker operation and the gaming lounge operation.

Product implication: The Venue should be modeled once, while analytics reporting should be separated through Business Units.

## Physical Spaces

### Space 1: Snooker Area

Approximate dimensions:

- North-south wall: 45 to 60 ft.
- West-east wall: 24 to 30 ft.

Purpose:

- Hosts snooker tables and related activity.
- Generates table occupancy, table activity, session, idle, and availability Events.

### Space 2: Connected Passage or Lobby

Approximate dimensions:

- To be measured during site survey.

Purpose:

- Connects snooker and gaming areas.
- Supports entry, movement, waiting, dwell, and shared traffic analysis.

Analytics attribution:

- Shared or neutral by default.
- Can later be attributed by rule if a clear business decision requires it.

### Space 3: Gaming Lounge Area

Approximate dimensions:

- North-south wall: 20 ft.
- West-east wall: 36 ft.

Purpose:

- Hosts gaming stations, consoles, PCs, seating areas, or other configured gaming Assets.
- Generates station occupancy, activity, session, idle, and availability Events.

## Business Units

### Business Unit 1: Snooker

Purpose:

- Separately track snooker activity, utilization, Sessions, Events, and operational performance.

Likely Assets:

- Snooker tables.
- Snooker waiting area if dedicated.
- Snooker counter or service point if dedicated.

Likely Sessions:

- Table usage Session.

Likely Events:

- Table became occupied.
- Table became available.
- Table activity started.
- Table activity stopped.
- Session started.
- Session ended.
- Long idle detected.

### Business Unit 2: Gaming Lounge

Purpose:

- Separately track gaming lounge activity, utilization, Sessions, Events, and operational performance.

Likely Assets:

- Gaming stations.
- Console stations.
- PC stations.
- Gaming waiting area if dedicated.

Likely Sessions:

- Station usage Session.

Likely Events:

- Station became occupied.
- Station became available.
- Station activity started.
- Station activity stopped.
- Session started.
- Session ended.
- Long idle detected.

### Shared or Neutral Area

Purpose:

- Track movement, waiting, or congestion without incorrectly assigning activity to snooker or gaming.

Likely Assets:

- Passage zone.
- Lobby zone.
- Shared waiting zone.
- Entry or exit zone.

Likely Events:

- Presence detected.
- Dwell threshold exceeded.
- Crowd or queue threshold exceeded.
- Movement between areas detected.

Attribution recommendation:

- Keep shared passage and lobby Events neutral at first.
- Attribute only when there is a business reason, such as measuring waiting customers for snooker versus gaming.

## Video Sources

The Venue has 12 cameras covering all spaces.

Each camera should be configured as a Video Source and assigned to the Space or Spaces it covers.

Known camera coverage from venue owner:

- Five cameras are inside the snooker club area.
- Four snooker cameras are mounted over two snooker tables, with two opposite-end views per table.
- One snooker camera covers the remaining two snooker tables, the snooker entry door, and the reception counter.
- One passage camera covers the passage and the outside of the snooker entry.
- One passage-entry camera covers the passage entry and the entry to the gaming lounge.
- In the gaming lounge, two cameras each cover two gaming stations.
- One gaming lounge camera covers two additional gaming stations.
- One gaming lounge camera covers the gaming reception area.
- One remaining camera role is still to be confirmed against the full 12-camera inventory.

The product should capture for each camera:

- Friendly name.
- Physical location.
- Covered Space.
- Covered Assets or Zones.
- Health status.
- Privacy masks if needed.
- Whether it supports snooker, gaming, shared passage, or multiple areas.

Important validation: 12 cameras sounds sufficient, but camera count is not the acceptance condition. Coverage quality is the acceptance condition.

Multi-camera Asset rule:

- Multiple cameras may contribute to one Asset.
- The dashboard should not duplicate the Asset just because two cameras see it.
- Analytics should count the table or station once.
- The product may use one camera as the primary view and another as a supporting view.
- If one angle is not useful, it may still be retained for health, review, or future tuning without driving the main Session logic.

## Initial Asset Types

Recommended Asset Types for this Venue:

- Snooker Table.
- Gaming Station.
- Waiting Area.
- Passage Zone.
- Entry Zone.
- Service Counter if applicable.
- Camera Equipment if the business wants to track cameras as operational Assets.

These are configuration examples only. The platform should still treat them as generic Asset Types.

## Initial Sensors

Recommended Sensors:

- Occupancy.
- Presence.
- Activity.
- Inactivity.
- Dwell.
- Count or queue estimate for waiting areas.
- Transition for passage movement where useful.
- Video Source health.

Deferred Sensors:

- Person identity.
- Face recognition.
- Staff identity tracking.
- Finance or revenue prediction.

## Flexible Observation Modes

The product must support different observation modes per Asset. It should not assume every gaming station, snooker table, or seating area can be observed in the same way.

Examples:

- Direct Asset view: the camera clearly sees the table, station, or activity area.
- Seated-person view: the camera can see a person sitting or standing at the Asset, but cannot see the screen or equipment clearly.
- Screen-visible view: the camera can see whether a TV, monitor, or display appears on, active, or idle.
- Area activity view: the camera can see movement or presence in a broader polygon, but not exact equipment interaction.
- Reception/counter view: the camera can observe presence, waiting, or service activity near a counter.

Reasoning: Some gaming lounge cameras may only show someone sitting on a sofa playing, while the TV or screen is not visible. That should still be useful for occupancy and session analytics, but the product should not claim screen activity if the screen is outside the view.

## Session Rules

### Snooker Table Usage Session

Starts when:

- The table Asset changes from available or idle to occupied or active for a configured minimum duration.

Ends when:

- The table Asset returns to available or inactive for a configured minimum duration.

Business Unit:

- Snooker.

Review:

- Sessions may be detected automatically.
- Managers can confirm, correct, or void Sessions.

### Gaming Station Usage Session

Starts when:

- The station Asset changes from available or idle to occupied or active for a configured minimum duration.

Ends when:

- The station Asset returns to available or inactive for a configured minimum duration.

Business Unit:

- Gaming Lounge.

Review:

- Sessions may be detected automatically.
- Managers can confirm, correct, or void Sessions.

### Shared Passage Dwell Session

Starts when:

- Presence is detected in a shared passage or lobby zone beyond a configured dwell threshold.

Ends when:

- The zone returns to clear for a configured minimum duration.

Business Unit:

- Neutral by default.

Review:

- Use for operational insight only, unless attribution rules are later approved.

## Dashboard Requirements

The Venue dashboard should support:

- All Venue view.
- Snooker Business Unit view.
- Gaming Lounge Business Unit view.
- Shared passage or lobby view.
- Camera health view.
- Active Sessions by Business Unit.
- Available and occupied Assets by Business Unit.
- Recent Events by Business Unit.
- Neutral shared Events.

The manager should be able to answer:

- How many snooker tables are occupied?
- How many gaming stations are occupied?
- Which Assets are available?
- Which Sessions are active?
- Is the passage or lobby crowded?
- Are all 12 cameras healthy?
- Which business line had more activity today?

## Analytics Requirements

Analytics should support separate tracking for:

- Snooker utilization.
- Gaming lounge utilization.
- Snooker Session count and duration.
- Gaming Session count and duration.
- Shared passage dwell or crowding.
- Asset idle time.
- Asset availability.
- Camera and Sensor health by Space.
- Business Unit comparison.

Analytics-only note:

Strikee Vision should provide operational attribution for separate analytics. It should not track revenue, billing, payments, taxes, ledgers, or accounting data in this phase.

## Acceptance Criteria

This Venue configuration is acceptable when:

- The full location can be represented as one Venue.
- Snooker and gaming can be represented as separate Business Units.
- The snooker area, gaming lounge, and passage can be represented as Spaces.
- Snooker tables and gaming stations can be configured as Assets.
- Shared passage activity can be tracked without forcing it into snooker or gaming analytics.
- Sessions and Events can be filtered by Business Unit.
- Dashboards can show combined Venue activity and separated Business Unit activity.
- Analytics can compare snooker and gaming activity without duplicating the Venue.
- Video Source health is visible for all 12 cameras.
- The product can mark uncertain or poorly covered areas as Unknown or Degraded.

## Site Survey Questions

Before implementation, collect:

- Number of snooker tables.
- Number and types of gaming stations.
- Exact passage or lobby dimensions.
- Camera names and positions.
- Which camera sees which Asset.
- Whether any camera views overlap.
- Whether any table or station has occlusion issues.
- Lighting conditions during operating hours.
- Whether analytics separation is by Asset, Session, Space, or manual review.
- Whether shared waiting should stay neutral or be attributed.

## Product Challenge

Do not model snooker and gaming as separate Venues if they are physically one location under one name. That would duplicate cameras, users, policies, dashboards, and shared passage data.

Use one Venue with multiple Business Units.
