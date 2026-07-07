# Venue Survey and MVP Scope

Status: Draft for site survey  
Purpose: Convert the generic Strikee Vision product specification into a practical first-version blueprint for the reference snooker and gaming venue.

This document is not implementation documentation. It defines what must be observed, configured, measured, and accepted before engineering begins.

## Product Position

The first version should prove that Strikee Vision can turn the existing 12-camera venue into useful operational analytics.

The product should answer:

- What is occupied right now?
- What is available right now?
- Which sessions are active?
- How much activity happened in snooker versus gaming?
- What is happening in the shared passage or lobby?
- Which cameras or sensors are degraded?
- Which data is trustworthy, uncertain, or missing?

The product should not answer:

- How much money was earned?
- Which payment method was used?
- Which customer paid?
- Which staff member handled a transaction?
- Any accounting, billing, tax, or ledger question.

## Venue Model

### Organization

Name: To be confirmed.

Purpose:

- Owns the Venue, users, roles, policies, and analytics access.

### Venue

Name: To be confirmed.

Purpose:

- Represents the full physical club under one business name.

### Business Units

Business Units are analytics segments only.

| Business Unit | Purpose | Included Assets | Shared Assets |
| --- | --- | --- | --- |
| Snooker | Track snooker usage, sessions, occupancy, and availability | Snooker tables, dedicated snooker waiting/service zones | Passage/lobby only if attribution rules are later approved |
| Gaming Lounge | Track gaming usage, sessions, occupancy, and availability | Gaming stations, consoles, PCs, dedicated gaming waiting/service zones | Passage/lobby only if attribution rules are later approved |
| Shared / Neutral | Track common movement, waiting, dwell, and crowding | Passage, lobby, entry/exit zones | Not attributed to snooker or gaming by default |

Decision: Use one Venue with multiple Business Units. Do not create separate Venues for snooker and gaming unless they are physically and operationally separate locations.

## Physical Spaces

### Space A: Snooker Area

Known dimensions:

- North-south wall: approximately 45 to 60 ft.
- West-east wall: approximately 24 to 30 ft.

Survey required:

- Exact length and width.
- Number of snooker tables.
- Table positions.
- Camera visibility for each table.
- Lighting consistency.
- Occlusion patterns from players, pillars, walls, furniture, or counters.
- Dedicated waiting area, if any.
- Dedicated service counter, if any.

### Space B: Connected Passage / Lobby

Known dimensions:

- Not yet measured.

Survey required:

- Exact length and width.
- Entrances and exits.
- Direction of movement between snooker and gaming.
- Waiting behavior.
- Whether customers stand, sit, queue, or pass through.
- Camera coverage and blind spots.
- Whether passage activity should remain neutral for analytics.

### Space C: Gaming Lounge Area

Known dimensions:

- North-south wall: approximately 20 ft.
- West-east wall: approximately 36 ft.

Survey required:

- Exact length and width.
- Number of gaming stations.
- Types of stations: PC, console, simulator, VR, or other.
- Station positions.
- Camera visibility for each station.
- Seating layout.
- Lighting consistency.
- Occlusion patterns from players, furniture, partitions, or screens.
- Dedicated waiting area, if any.

## Camera Survey

There are 12 cameras covering the full Venue.

For each camera, capture:

| Camera | Physical Location | Primary Space | Secondary Space | Visible Assets | Blind Spots | Quality Notes | MVP Useful? |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Snooker Table 1 Camera A | Mounted over table, end A | Snooker Area | None expected | Snooker Table 1 | TBD | One of two opposite-end views for same table | High |
| Snooker Table 1 Camera B | Mounted over table, end B | Snooker Area | None expected | Snooker Table 1 | TBD | Supporting opposite-end view for same table | Medium |
| Snooker Table 2 Camera A | Mounted over table, end A | Snooker Area | None expected | Snooker Table 2 | TBD | One of two opposite-end views for same table | High |
| Snooker Table 2 Camera B | Mounted over table, end B | Snooker Area | None expected | Snooker Table 2 | TBD | Supporting opposite-end view for same table | Medium |
| Snooker Multi-Asset Camera | TBD | Snooker Area | Snooker entry / reception | Snooker Tables 3 and 4, snooker entry door, reception counter | TBD | Multi-asset view; needs separate polygons | High |
| Passage Camera A | TBD | Connected Passage / Lobby | Outside snooker entry | Passage and outside of snooker entry | TBD | Useful for movement, dwell, and entry context | High |
| Passage Camera B | TBD | Connected Passage / Lobby | Gaming lounge entry | Passage entry and gaming lounge entry | TBD | Useful for transition and shared-area context | High |
| Gaming Camera A | TBD | Gaming Lounge Area | None expected | Two gaming stations | TBD | Station pair view | Later |
| Gaming Camera B | TBD | Gaming Lounge Area | None expected | Two gaming stations | TBD | Station pair view | Later |
| Gaming Camera C | TBD | Gaming Lounge Area | None expected | Two additional gaming stations | TBD | Station pair view | Later |
| Gaming Camera D | TBD | Gaming Lounge Area | Gaming reception | Gaming reception area | TBD | Reception / waiting / service view | Later |
| Camera 12 | TBD | TBD | TBD | TBD | TBD | Role not yet described | TBD |

Quality notes should capture:

- Is the camera fixed?
- Is the angle stable?
- Is the image clear during operating hours?
- Is the frame too wide or too narrow?
- Is the camera too high, too low, or too angled?
- Can the relevant Asset be separated from background activity?
- Does the camera see the Asset continuously or only partially?
- Does lighting change significantly by time of day?

Product rule: Camera count does not define success. Useful coverage defines success.

Known coverage summary:

- Snooker can start first because the four tables have described coverage.
- Snooker has five described cameras: four cameras over two tables, plus one multi-asset camera for two tables, entry, and reception.
- Gaming lounge setup can be completed later because the lounge is still being built.
- One camera from the 12-camera inventory still needs its role confirmed.
- Multiple cameras covering the same table should be clubbed into one Asset coverage model, not shown as duplicate tables.
- Cameras covering multiple Assets must use separate polygons or zones so one camera can support multiple independent Assets.

## Multi-Camera Asset Coverage

Some Assets may have more than one camera view. This is useful, but it must not duplicate the operational truth.

| Asset | Primary Video Source | Supporting Video Source | Product Behavior |
| --- | --- | --- | --- |
| Snooker Table 1 | Snooker Table 1 Camera A | Snooker Table 1 Camera B | One table State, one Event stream, one Session timeline |
| Snooker Table 2 | Snooker Table 2 Camera A | Snooker Table 2 Camera B | One table State, one Event stream, one Session timeline |

Product rules:

- The Asset is the business object; cameras are evidence sources.
- Multiple camera observations should support one derived State.
- The dashboard may show only the primary view by default.
- Supporting views can be used for confidence, review, or fallback.
- If a supporting camera adds no business value, it should not be required for MVP decisions.
- Analytics must count each table once even if two cameras observe it.

## Observation Capability Model

The product must support flexible observation capabilities per Asset. Not every Asset will have the same kind of visual evidence.

| Observation Capability | Meaning | Useful For | Limitation |
| --- | --- | --- | --- |
| Direct Asset View | Camera clearly sees the Asset area | Occupancy, activity, session start/end | Best case, but not always available |
| Seated Person View | Camera sees someone sitting or standing at the Asset | Occupancy and session approximation | Cannot prove screen or equipment state |
| Screen / TV Visible View | Camera can see whether a screen or TV appears active | Screen activity and idle clues | May not identify who is using it |
| Area Activity View | Camera sees movement or presence in a broader zone | General activity and dwell | Less precise per Asset |
| Reception / Counter View | Camera sees people near a counter | Waiting, service presence, queue | Not a table/station session signal by itself |
| Entry / Transition View | Camera sees a doorway or passage threshold | Movement and flow | Should not imply Asset usage alone |

Product rule: A Sensor should only claim what the camera can actually support. If a camera only sees someone seated on a sofa but not the TV, the product may infer occupancy or a session candidate, but it should not claim TV activity.

## Asset Inventory

### Snooker Assets

| Asset | Asset Type | Space | Business Unit | Camera Coverage | MVP Priority | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Snooker Table 1 | Snooker Table | Snooker Area | Snooker | Snooker Table 1 Camera A + Camera B | High | Two opposite-end camera views clubbed into one table Asset |
| Snooker Table 2 | Snooker Table | Snooker Area | Snooker | Snooker Table 2 Camera A + Camera B | High | Two opposite-end camera views clubbed into one table Asset |
| Snooker Table 3 | Snooker Table | Snooker Area | Snooker | Snooker Multi-Asset Camera | High | Shares camera with Table 4, entry door, and reception counter |
| Snooker Table 4 | Snooker Table | Snooker Area | Snooker | Snooker Multi-Asset Camera | High | Shares camera with Table 3, entry door, and reception counter |

Update table numbers and camera names after the site survey if the physical labels differ.

### Gaming Assets

| Asset | Asset Type | Space | Business Unit | Camera Coverage | MVP Priority | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Gaming Station 1 | Gaming Station | Gaming Lounge Area | Gaming Lounge | Gaming Camera A | Later | Shares camera with Station 2 |
| Gaming Station 2 | Gaming Station | Gaming Lounge Area | Gaming Lounge | Gaming Camera A | Later | Shares camera with Station 1 |
| Gaming Station 3 | Gaming Station | Gaming Lounge Area | Gaming Lounge | Gaming Camera B | Later | Shares camera with Station 4 |
| Gaming Station 4 | Gaming Station | Gaming Lounge Area | Gaming Lounge | Gaming Camera B | Later | Shares camera with Station 3 |
| Gaming Station 5 | Gaming Station | Gaming Lounge Area | Gaming Lounge | Gaming Camera C | Later | Shares camera with Station 6 |
| Gaming Station 6 | Gaming Station | Gaming Lounge Area | Gaming Lounge | Gaming Camera C | Later | Shares camera with Station 5 |

The gaming lounge is still under setup, so these Assets are planned but not MVP-start blockers.

### Shared Assets

| Asset | Asset Type | Space | Business Unit | Camera Coverage | MVP Priority | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Passage Zone | Passage Zone | Connected Passage / Lobby | Shared / Neutral | TBD | High | Movement and dwell |
| Lobby / Waiting Zone | Waiting Area | Connected Passage / Lobby | Shared / Neutral | TBD | Medium | Only if customers wait here |
| Entry Zone | Entry Zone | Connected Passage / Lobby | Shared / Neutral | TBD | Medium | Only if visible |
| Snooker Reception Counter | Service Counter | Snooker Area | Snooker | Snooker Multi-Asset Camera | Medium | Presence, waiting, or service activity only |
| Gaming Reception Counter | Service Counter | Gaming Lounge Area | Gaming Lounge | Gaming Camera D | Later | Configure after gaming lounge setup |

## MVP Analytics Scope

### Must Have

The MVP should provide:

- Live occupied and available status for high-priority snooker tables.
- Live occupied and available status for gaming stations after the gaming lounge layout is ready.
- Active Sessions for snooker tables.
- Active Sessions for gaming stations after station mapping is ready.
- Session count and duration by Business Unit.
- Utilization by Business Unit.
- Asset idle or inactive duration.
- Shared passage presence or dwell.
- Camera health for all 12 Video Sources.
- Unknown or Degraded status when coverage is not reliable.

Reasoning: These answer the real operating questions without pulling the product into finance, identity, or overbuilt AI.

### Should Have

The MVP should include if coverage supports it:

- Waiting or crowd threshold in the passage/lobby.
- Movement direction between snooker and gaming.
- Daily and weekly trend view.
- Review queue for uncertain Sessions.
- Manager correction of Session start/end.

### Not MVP

The MVP should exclude:

- Revenue tracking.
- Payment tracking.
- Customer identity.
- Face recognition.
- Staff performance scoring.
- Full accounting.
- Exact customer-level billing.
- Predictive forecasting.
- Fully automated attribution of shared passage activity.
- Claiming screen or TV activity when the camera cannot see the screen or TV.

## MVP Events

### Snooker Events

- Snooker table became occupied.
- Snooker table became available.
- Snooker table activity started.
- Snooker table activity stopped.
- Snooker Session started.
- Snooker Session ended.
- Snooker table state became Unknown.
- Snooker table state became Degraded.

### Gaming Events

- Gaming station became occupied.
- Gaming station became available.
- Gaming station activity started.
- Gaming station activity stopped.
- Gaming Session started.
- Gaming Session ended.
- Gaming station state became Unknown.
- Gaming station state became Degraded.

### Shared Events

- Passage presence detected.
- Passage dwell threshold exceeded.
- Shared waiting/crowd threshold exceeded.
- Entry or exit movement detected, if reliable.

### Health Events

- Camera became offline.
- Camera became degraded.
- Camera recovered.
- Sensor confidence became degraded.
- Sensor recovered.

## MVP Session Rules

### Snooker Table Session

Start candidate:

- Occupancy or activity is detected around a snooker table for a minimum configured duration.

End candidate:

- Occupancy or activity clears for a minimum configured duration.

Analytics attribution:

- Business Unit: Snooker.

Review behavior:

- Automatically detected.
- Can be confirmed, corrected, or voided.

### Gaming Station Session

Start candidate:

- Occupancy, seated presence, or activity is detected around a gaming station for a minimum configured duration.

End candidate:

- Occupancy, seated presence, or activity clears for a minimum configured duration.

Analytics attribution:

- Business Unit: Gaming Lounge.

Review behavior:

- Automatically detected.
- Can be confirmed, corrected, or voided.

Observation caveat:

- If the TV or screen is not visible, the Session should be labeled as occupancy-based or seated-presence-based rather than screen-activity-based.

### Shared Passage Dwell

Start candidate:

- Presence remains in passage/lobby beyond a configured dwell threshold.

End candidate:

- Presence clears for a minimum configured duration.

Analytics attribution:

- Business Unit: Shared / Neutral.

Review behavior:

- Operational insight only.
- Not used to attribute snooker or gaming activity in MVP.

## MVP Dashboard Scope

The first dashboard should include:

- Venue overview.
- Business Unit selector: All, Snooker, Gaming Lounge, Shared / Neutral.
- Live Asset grid.
- Active Sessions.
- Recent Events.
- Camera health.
- Unknown and Degraded areas.
- Today summary.

### Venue Overview

Shows:

- Total active Sessions.
- Occupied Assets.
- Available Assets.
- Unknown or Degraded Assets.
- Cameras offline or degraded.
- Recent high-priority Events.

### Snooker View

Shows:

- Snooker table occupancy.
- Active snooker Sessions.
- Snooker utilization today.
- Snooker idle/available Assets.
- Snooker Events.

### Gaming Lounge View

Shows:

- Gaming station occupancy.
- Active gaming Sessions.
- Gaming utilization today.
- Gaming idle/available Assets.
- Gaming Events.

### Shared / Neutral View

Shows:

- Passage/lobby presence.
- Dwell or crowd warnings.
- Entry/exit movement if reliable.
- Shared Events.

## MVP Analytics Scope

The first analytics view should include:

- Utilization by Business Unit.
- Session count by Business Unit.
- Average Session duration by Business Unit.
- Occupied time by Asset.
- Available time by Asset.
- Unknown or Degraded time by Asset.
- Camera uptime.
- Sensor confidence issues.
- Shared passage dwell or crowding.

Time filters:

- Today.
- Yesterday.
- Last 7 days.
- Custom range.

Required dimensions:

- Business Unit.
- Space.
- Asset Type.
- Asset.
- Event Type.
- Session Type.
- Camera.
- State.

## Good Enough Acceptance Criteria

The MVP is good enough when:

- High-priority snooker tables can show occupied, available, active, idle, unknown, or degraded State.
- Gaming stations can be added later using the same configuration model after the gaming lounge is ready.
- Snooker and gaming Sessions can be separated in analytics.
- Shared passage activity can be tracked without forcing it into snooker or gaming.
- Camera health is visible for all 12 cameras.
- The dashboard makes unreliable coverage visible rather than hiding it.
- Managers can review and correct detected Sessions.
- Analytics can answer snooker vs gaming usage without finance data.
- The product can operate from local video by default.

## Detection Quality Targets

These targets should be reviewed after real camera samples are inspected.

### Occupancy State

Target:

- The product should correctly identify occupied versus available for high-priority Assets during normal operating conditions.

Allowed uncertainty:

- Unknown or Degraded is acceptable when the camera view is blocked, lighting is poor, or the Asset is not clearly visible.

### Session Timing

Target:

- Session start and end should be close enough for operational analytics.

Important clarification:

- MVP does not require billing-grade timing.
- Human correction should be available for Sessions that matter.

### Shared Passage

Target:

- The product should detect presence and dwell in shared areas where camera coverage is clear.

Allowed uncertainty:

- The product should not guess whether a person belongs to snooker or gaming unless a clear attribution rule is approved.

### Camera Health

Target:

- Camera offline or degraded conditions should be visible quickly enough for staff to know analytics may be affected.

## Open Questions for Site Survey

### Layout

- What is the exact size of the snooker area?
- What is the exact size of the gaming lounge?
- What is the exact size and shape of the passage/lobby?
- Are there pillars, partitions, counters, furniture, or blind corners?

### Snooker

- How many snooker tables are there?
- Are all tables equally important for MVP?
- Can each table be seen by at least one camera?
- Is activity around the table visible, or only the table surface?
- Is there a dedicated waiting area?

### Gaming

- How many gaming stations are there?
- What types of stations exist?
- Are stations seated, standing, or mixed?
- Can each station be seen by at least one camera?
- Are screens, chairs, or partitions blocking views?

### Passage / Lobby

- Is the passage mostly movement, waiting, or both?
- Do people wait there before snooker, gaming, or both?
- Should shared activity remain neutral for MVP?
- Are there clear entry and exit points?

### Cameras

- Where are all 12 cameras mounted?
- Which cameras cover multiple Spaces?
- Which cameras overlap?
- Which cameras are essential for MVP?
- Are camera feeds fixed and stable?
- Are there low-light periods?

### Operations

- What decisions should the manager make from the dashboard?
- What analytics are needed daily?
- What analytics are needed weekly?
- Which Events should create notifications?
- Who will review uncertain Sessions?

## Recommended MVP Cut

The first version should focus on:

- 100 percent of cameras represented as Video Sources.
- Four snooker tables first.
- Snooker entry, snooker reception, and shared passage context.
- Gaming lounge camera and Asset configuration after the lounge layout is ready.
- Shared passage presence and dwell only where camera coverage is clear.
- Business Unit analytics for Snooker, Gaming Lounge, and Shared / Neutral.
- Session review and correction.
- Health and degraded-state visibility.

Do not force every table, station, or zone into MVP if camera coverage is poor. A smaller accurate MVP is better than a full-venue dashboard that users cannot trust.
