# Product Bible

## Product Statement

Strikee Vision is an Operations Intelligence Platform that transforms existing CCTV and video feeds into real-time operational insight for physical venues.

The product watches configured spaces, detects operational observations, converts those observations into state changes and immutable events, and uses those events to power dashboards, analytics, sessions, alerts, and business decisions.

Strikee Vision is not a generic CCTV viewer. It is not a video archive product. It is not a surveillance-first product. It is an operational decision system that uses video as one possible input.

## Target Customers

Strikee Vision serves operators of physical venues where visibility, utilization, staffing, service quality, asset usage, safety, or queue flow matter.

Initial strong-fit categories:

- Gaming lounges.
- Snooker clubs.
- Arcades.
- Restaurants.
- Cafes.
- Warehouses.
- Offices.
- Shared recreational venues.

The product must remain category-neutral. A gaming station, snooker table, reception counter, loading bay, waiting area, office desk cluster, cafe table, or arcade machine is configured as an Asset. None of these should be hardcoded as product concepts.

## Core Customer Problems

Physical venue operators often have video, but not operational intelligence.

Common problems:

- Staff cannot see all operational activity in real time.
- Asset usage is not measured accurately.
- Operators rely on manual logs, memory, or incomplete usage records.
- Queues, idle resources, service delays, and abnormal behavior are noticed late.
- Management lacks reliable historical insight.
- Video review is expensive, manual, and reactive.
- Existing CCTV systems preserve footage but do not produce business events.

## Product Promise

Strikee Vision helps operators answer:

- What is happening now?
- Which assets are occupied, idle, blocked, waiting, or unavailable?
- When did an activity start and end?
- Which sessions occurred?
- Which events need attention?
- Where are bottlenecks forming?
- How did the venue perform over time?
- What changed, and why?

## Non-Goals

Strikee Vision should not become:

- A law-enforcement surveillance platform.
- A facial recognition product.
- A generalized video editing or video storage platform.
- A hardcoded vertical product for only gaming or snooker.
- A brittle automation engine where AI output directly mutates business truth.
- A high-cost cloud video processing system by default.
- A product that requires perfect camera placement to provide any value.

## Product Thesis

The core product bet is that most physical venues already have enough visual signal to derive useful operational events if configuration is simple, video remains local, and the software treats AI as an observer rather than a decision authority.

AI can say, "I observed activity in this polygon with this confidence."  
The product decides, "Asset A became occupied at 14:03, then generated a Session that ended at 15:12."

This separation makes the product more reliable, auditable, and adaptable.

## Core Domain Chain

The product is organized around this conceptual chain:

Organization  
to Venue  
to Space  
to Video Source  
to Asset  
to Sensor  
to Observation  
to State  
to Event  
to Session

This chain is not only data structure. It is the product's mental model:

- Organizations own operations.
- Venues contain physical operations.
- Spaces define where things happen.
- Video Sources provide visual input.
- Assets define what the business cares about.
- Sensors define what should be observed.
- Observations capture AI output.
- States represent current operational truth.
- Events record immutable business facts.
- Sessions group events into meaningful periods.

## Strong Product Opinions

### Local First

Video should be processed locally by default because bandwidth, privacy, latency, and cost are core commercial constraints.

Reasoning: Many venues will reject continuous cloud video upload. Local-first lowers operating cost and increases trust.

### Cloud Optional

Cloud capabilities may provide remote dashboards, cross-venue analytics, backup, managed configuration, or notifications, but the product must still provide value without requiring cloud video processing.

Reasoning: Optional cloud allows commercial expansion without making the base product fragile or expensive.

### AI Observes, Software Decides

AI output should be treated as evidence, not business truth.

Reasoning: AI can be uncertain. Business decisions need deterministic rules, auditability, thresholds, and override paths.

### Configuration Over Code

Venue-specific differences should be modeled through configuration.

Reasoning: Commercial scale requires onboarding varied physical venues without custom engineering for every layout.

### Events Are Immutable

Once created, an Event is not edited in place. Corrections create additional correction or override Events.

Reasoning: Operators need trust, auditability, and historical consistency.

### Everything Business-Relevant Is an Asset

Anything the business wants to observe, report on, assign responsibility for, or operate around should be represented as an Asset.

Reasoning: This keeps the product generic while letting customers model their own world.

Challenge: The word "everything" should not mean every internal technical object becomes an Asset. Video Sources, policies, users, and notification rules are product objects. They may be linked to Assets but should not be forced into the Asset model unless the customer has a business reason to manage them as assets.

## Product Boundaries

### Included

- Organization and venue management.
- Space and layout modeling.
- Video source registration and health.
- Asset configuration.
- Sensor configuration.
- Polygon and zone definition.
- Observation ingestion.
- State derivation.
- Event generation.
- Session detection.
- Operational dashboards.
- Analytics.
- Notifications.
- Audit trails.
- Privacy controls.
- Manual review and correction.

### Excluded From Initial Scope Unless Later Approved

- Face identification.
- Employee productivity scoring by identity.
- Audio analytics.
- Payment processing.
- Full CCTV recording replacement.
- Building access control.
- Robotic process automation.
- General-purpose BI builder.
- Industry-specific hardcoded modules.

## Commercial Positioning

Strikee Vision should be positioned as:

- Operations intelligence for venues with existing cameras.
- Faster awareness without replacing CCTV.
- Local-first analytics.
- Configurable asset and event intelligence.
- A practical operating layer between camera systems and business decisions.

It should not be positioned as:

- "AI surveillance."
- "A camera system."
- "Gaming lounge software."
- "An all-in-one ERP."

## Product Success Metrics

Product-level metrics:

- Time to first useful event after setup.
- Percentage of assets with reliable state detection.
- Event accuracy after review.
- Reduction in manual checks.
- Notification precision.
- Session detection accuracy.
- Operator dashboard adoption.
- Number of decisions made from events.
- Cost per venue per month to operate.
- Percentage of video retained locally.

## Assumptions to Challenge

### Assumption: CCTV feeds are always good enough.

Reality: Camera placement, lighting, occlusion, angle, and frame rate vary widely.

Product response: The product must expose camera suitability checks, confidence, calibration warnings, and fallback manual workflows.

### Assumption: Sessions can always be inferred.

Reality: Some venues have ambiguous activity patterns.

Product response: Sessions should be configurable and confidence-scored. The product should support "detected", "confirmed", and "corrected" session states.

### Assumption: Real-time means instant.

Reality: Operators usually need useful freshness, not millisecond latency.

Product response: Define real-time operationally as insight delivered quickly enough to act, with provisional product targets documented in the [Acceptance Criteria](11-acceptance-criteria.md) (to be validated after camera sampling).

### Assumption: More AI categories mean more product value.

Reality: More categories increase setup complexity and false positives.

Product response: Prioritize high-value, generic operational observations: presence, occupancy, activity, inactivity, queue, dwell, transition, and obstruction.

### Assumption: All customers want cloud dashboards.

Reality: Some customers want fully local operation.

Product response: Cloud must remain optional, and local operation must have a complete core workflow.

## Product North Star

The product succeeds when a venue operator can configure their physical operation once, trust the system to generate useful Events, and run daily decisions from those Events without watching video constantly.
