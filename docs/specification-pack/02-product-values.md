# Product Values

## 1. Reliable Over Clever

The product should prefer simple, explainable behavior over impressive but fragile automation.

Reasoning: Venue operators need trust. A simple event rule that works consistently is more valuable than a complex prediction that cannot be explained.

Product implications:

- Show why an Event was created.
- Expose confidence and evidence.
- Allow correction.
- Avoid hidden autonomous decisions.

## 2. Local First

The product should work in a local venue environment and keep video local by default.

Reasoning: Video is sensitive, large, and expensive to transmit. Local-first design improves privacy, latency, resilience, and cost.

Product implications:

- Local dashboard should remain useful during internet outages.
- Video upload should require explicit configuration.
- Cloud features should sync metadata and Events before video.
- Product language should make locality visible to users.

Notifications are tiered so local operation stays useful offline. In-app and on-screen notifications always work offline. Network channels (email, SMS, webhook) are best-effort: when offline they are queued and retried on reconnect, with a visible "delivery degraded" indicator so nothing fails silently. Every Critical notification rule must include at least one local channel, so a critical alert can never depend solely on the internet.

## 3. Privacy First

The product should minimize personal data collection and avoid identity-centric features unless explicitly approved in the future.

Reasoning: Commercial venues can gain operational insight without identifying individuals.

Product implications:

- Prefer occupancy and activity signals over person identity.
- Avoid face recognition as a default capability.
- Provide masking, retention, and access controls.
- Record who viewed or exported sensitive evidence.

## 4. Configuration Over Code

Venue-specific behavior should be modeled with configuration.

Reasoning: The product must scale across venue categories without custom builds.

Product implications:

- Asset types are configurable.
- Session rules are configurable.
- Polygons and zones are configurable.
- Notification rules are configurable.
- Dashboards adapt to configured entities.

Configuration means a fixed catalog of parameterized rule templates, not a free-form rule builder. Users tune numbers and choices (thresholds, durations, schedules, recipients) within predefined templates; they cannot author arbitrary logic. Adding a new kind of rule is a product/engineering action, not a user action. Every template ships with sensible defaults and an ON/OFF switch, so a venue can go live on defaults, disable rules it does not want, and adjust numbers only where reality demands it.

## 5. Events Are the Source of Business Truth

Business decisions should be based on immutable Events, not transient AI observations.

Reasoning: Events are auditable, reviewable, and stable enough for dashboards, analytics, and notifications.

Product implications:

- Observations feed state.
- State transitions generate Events.
- Sessions are derived from Events.
- Corrections are recorded as Events.
- Analytics aggregate Events.

## 6. Human Override Is a Feature

The product should let authorized users confirm, correct, suppress, or annotate operational facts.

Reasoning: Physical operations have ambiguity. A system that cannot be corrected loses trust.

Product implications:

- Manual corrections must not rewrite history.
- Override reasons should be captured.
- The UI should distinguish detected, confirmed, and corrected facts.
- Corrections should improve future configuration decisions where appropriate.

## 7. Generic Does Not Mean Vague

The product must be generic across venue types but precise in its internal language.

Reasoning: Generic products fail when they become abstract to the point that users cannot configure or understand them.

Product implications:

- Provide plain, configurable asset labels.
- Use examples in onboarding without hardcoding examples.
- Make object purpose clear.
- Keep a controlled vocabulary.

## 8. Low Operating Cost

The product should minimize compute, bandwidth, storage, support, and setup cost.

Reasoning: Physical venue operators are often cost-sensitive, and margin can disappear if video processing is overbuilt.

Product implications:

- Process only configured areas where possible.
- Store Events and evidence metadata by default, not unnecessary full video copies.
- Provide health checks to prevent silent failure.
- Prefer configuration reuse across similar spaces.

## 9. Auditable by Design

Users should be able to understand what happened, when, where, and why the product decided something.

Reasoning: Operational decisions affect utilization, staffing, service, and trust.

Product implications:

- Every Event has origin, evidence, timestamp, source, and rule context.
- Configuration changes are logged.
- Notifications link back to Events.
- Session timelines are explainable.

## 10. Customer Control

Customers should control what is observed, when, how long evidence is retained, and who can access it.

Reasoning: Different venues have different privacy obligations and operational tolerances.

Product implications:

- Observation policies are configurable.
- Retention policies are configurable.
- Sensitive zones can be masked or disabled.
- User permissions are explicit.
