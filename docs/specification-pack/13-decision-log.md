# Decision Log

This log records product decisions made during specification. It should be updated whenever the product direction changes.

## D001: Product Category

Decision: Strikee Vision is an Operations Intelligence Platform.

Reasoning: This positions the product around business operations and decisions, not surveillance or CCTV storage.

Status: Accepted.

## D002: Generic Domain Model

Decision: The product will remain generic across physical venues.

Reasoning: Gaming stations, snooker tables, restaurant tables, counters, shelves, bays, and waiting areas are configuration, not code.

Status: Accepted.

## D003: Local-First Default

Decision: Video stays local by default.

Reasoning: Privacy, bandwidth, latency, cost, and customer trust all favor local video handling.

Status: Accepted.

## D004: Cloud Optional

Decision: Cloud features are optional extensions, not required for core operation.

Reasoning: Some customers will reject mandatory cloud video processing, and local-first operation is a core differentiator.

Status: Accepted.

## D005: AI Observes, Software Decides

Decision: AI outputs Observations. Product rules decide States, Events, Sessions, and Notifications.

Reasoning: This improves reliability, auditability, explainability, and control.

Status: Accepted.

## D006: Immutable Events

Decision: Events are immutable. Corrections create new Events.

Reasoning: Business decisions require auditability and historical trust.

Status: Accepted.

## D007: Everything Business-Relevant Is an Asset

Decision: Anything business-relevant that can be configured, observed, assigned, measured, or reported on is modeled as an Asset.

Reasoning: This gives the product a generic operating model.

Clarification: Not every internal product object should be forced into Asset. Video Source, User, Rule, and Policy remain distinct product concepts unless the customer also manages them as Assets.

Status: Accepted with clarification.

## D008: Sessions Are Derived, Not Primary

Decision: Sessions are derived from Events and rules.

Reasoning: Sessions need auditable start and end facts. Events are the stable source of truth.

Status: Accepted.

## D009: Unknown Is a First-Class State

Decision: Unknown must be represented explicitly.

Reasoning: Physical observation can fail. Honest uncertainty is safer than false certainty.

Status: Accepted.

## D010: No Identity Recognition in Default Scope

Decision: Face recognition, demographic inference, emotion inference, and identity tracking are excluded from default scope.

Reasoning: These features add privacy, legal, commercial, and trust risk without being necessary for core operational value.

Status: Accepted.

## D011: Conceptual ERD Only

Decision: The specification includes a conceptual ERD only.

Reasoning: Database technology should be selected later based on implementation requirements.

Status: Accepted.

## D012: Templates Are Configuration Packages

Decision: Future industry templates should be editable configuration packages, not hardcoded product branches.

Reasoning: Templates reduce setup effort while preserving generic product architecture.

Status: Accepted.

## D013: Notifications Must Link to Events

Decision: Notifications should be triggered by Events or persistent State conditions, not raw Observations.

Reasoning: This reduces noise and keeps alerts explainable.

Status: Accepted.

## D014: Analytics Come From Events, Sessions, and Metric Samples

Decision: Analytics should aggregate Events, Sessions, and Metric Samples rather than raw video. Metric Samples are periodic scalar snapshots (occupancy count, confidence, queue estimate, health) emitted on each processing tick, used for scalar and time-series metrics that Events and Sessions cannot produce.

Reasoning: This is lower cost, more private, more auditable, and easier to explain. Adding Metric Samples closes the gap for average, peak, and by-hour metrics while preserving the no-raw-video principle. See Gaps G04.

Status: Accepted (amended).

## D015: Rules Are a Fixed Catalog of Parameterized Templates

Decision: Rules are a fixed catalog of parameterized templates (occupancy, activity, session, threshold, health, notification). Users tune numbers and choices only; there is no free-form rule builder. Each template ships with sensible defaults and an ON/OFF switch. Adding a new kind of rule is a product and engineering action, not a user action. A small expression layer for advanced users may be added later on top of the catalog.

Reasoning: A fully arbitrary rule engine is hard to understand, test, and support. Parameterized templates are explainable, cheap to evaluate on the periodic tick, and cover every reference scenario with different numbers rather than different logic. See Gaps G06.

Status: Accepted.

## D016: Separate Physical Spaces From Business Units

Decision: Strikee Vision will model Business Units separately from Spaces.

Reasoning: A single Venue may contain multiple business lines under the same brand, such as a snooker operation and a gaming lounge, while sharing a passage, lobby, entrance, cameras, staff, or policies. Spaces describe physical layout. Business Units describe operational analytics attribution.

Status: Accepted.

## D017: Business Unit Is Analytics Only

Decision: Business Unit tracking provides attribution for Events, Sessions, Assets, dashboards, and analytics only. Strikee Vision should not track finance, payment, billing, tax, ledger, or accounting data in this phase.

Reasoning: The product should track operational truth needed for separate analytics without taking on finance workflows that are outside the product's purpose.

Status: Accepted.

## D018: Sensor Is First-Class, Owned by the Asset

Decision: A Sensor is a first-class object referencing a subject (Asset), an evidence source (Video Source), and a spatial scope (Zone). Its lifecycle home is the Asset. Space and passage areas are modeled as Assets so a Sensor's subject is always an Asset. Camera health is a property of the Video Source, not a Sensor.

Reasoning: Removes the four-way ownership ambiguity. See Gaps G01.

Status: Accepted.

## D019: Multi-Camera Coverage via Primary and Supporting Sensors

Decision: When multiple cameras observe one Asset, each is a Sensor with a role of primary or supporting. The primary decides State; supporting sensors add confidence, review, and fallback. Presence override: the Asset is occupied if the primary reports occupied or any supporting sensor reports occupied with high confidence. Weighted fusion is deferred.

Reasoning: Gives one Asset one State from many cameras, explainably. See Gaps G02.

Status: Accepted.

## D020: State Is Three Facets

Decision: State is a structured object with three facets — presence, activity, health — each with its own value, confidence, and effective time. The dashboard shows one derived label, with health taking priority.

Reasoning: Presence and activity are independent axes; health must not corrupt business status. See Gaps G03.

Status: Accepted.

## D021: Sessions Are Materialized with a Grace Window

Decision: Sessions are materialized records. A session opens after presence or activity holds for the Asset Type's minimum start duration and closes after it clears for the minimum clear duration (grace window). After close, late activity starts a new session; humans merge via correction Events; corrections are append-only.

Reasoning: Defines correctness under late and out-of-order observations. See Gaps G05.

Status: Accepted.

## D022: One Session, One Asset, One Business Unit

Decision: In this phase a session belongs to exactly one Asset and therefore one Business Unit. Shared areas are their own neutral-Business-Unit sessions. Cross-Business-Unit journeys are a later analytics feature.

Reasoning: Keeps Business Unit analytics clean. See Gaps G08.

Status: Accepted.

## D023: Provisional Performance Targets

Decision: Acceptance criteria carry provisional numeric targets (state freshness, stale-to-Unknown, occupancy accuracy, session timing, camera-down visibility, dashboard load), tagged for validation after real camera sampling.

Reasoning: Makes "real-time" and "reliable" testable. See Gaps G09.

Status: Accepted.

## D024: Local-First Tiered Notifications

Decision: In-app and on-screen notifications always work offline. Network channels are best-effort, queued and retried on reconnect, with a visible delivery-degraded indicator. Every Critical rule must include at least one local channel.

Reasoning: Keeps the local-first promise honest for alerts. See Gaps G10.

Status: Accepted.

## D025: Evidence Availability Status and Retained Keyframe

Decision: Each evidence reference carries an availability status (available, expired, masked). On Event creation a small keyframe is retained on the longer Event retention while full clips follow the shorter video retention. Masked zones are never snapshotted.

Reasoning: Prevents dangling evidence links and keeps review useful after clips expire. See Gaps G11.

Status: Accepted.

## D026: Zone Is the Only Linkable Spatial Object

Decision: Zone is the only named, linkable spatial object; it owns one or more polygons. Assets and Sensors link to Zones, never to bare polygons.

Reasoning: Removes the Zone/Polygon overlap. See Gaps G12.

Status: Accepted.

## D027: One-Level Space Nesting for MVP

Decision: Space nesting is limited to one level for MVP; roll-up is the simple sum of a Space's assets. Deeper nesting is deferred.

Reasoning: Avoids analytics complexity with no MVP benefit. See Gaps G15.

Status: Accepted.

## Open Decisions

### O001: First Beachhead Venue Category

Question: Which venue category should validate the first commercial version?

Options:

- Gaming or recreational venue.
- Snooker or table-based venue.
- Cafe or restaurant.
- Warehouse or logistics.
- Office occupancy.

Recommendation: Select one or two beachhead categories for go-to-market while keeping product configuration generic.

Resolution: The reference snooker-and-gaming venue is the first beachhead. Snooker tables lead the MVP; the gaming lounge follows once its layout is ready. Model stays generic.

### O002: Minimum Useful Event Set

Question: Which Events are required for the first sellable product?

Recommendation: Start with source health, asset occupied, asset available, asset active, asset idle, threshold exceeded, session started, session ended, manual correction, notification acknowledged.

### O003: Evidence Retention Defaults

Question: What default evidence retention period should be recommended?

Recommendation: Keep full video local under customer control. Store Event metadata longer than evidence clips. Choose final defaults only after legal and customer review.

### O004: Review Workflow Strictness

Question: Should detected Sessions require human confirmation before analytics?

Recommendation: Allow both modes. Use detected Sessions by default with confidence visible, and let higher-risk customers require confirmation.

### O005: Shared Space Attribution

Question: How should shared passage or lobby activity be attributed between Business Units?

Recommendation: Support neutral shared reporting first. Add attribution rules only where there is a clear business decision, such as assigning waiting time to the next used Asset or splitting shared traffic by destination.

Resolution: Shared passage and lobby activity stays neutral (Shared / Neutral Business Unit) by default, tracked as its own sessions. Attribution to snooker or gaming is deferred to a later analytics feature. See D022 and Gaps G08.
