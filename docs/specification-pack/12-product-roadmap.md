# Product Roadmap

## Roadmap Principles

- Build the generic core before vertical-specific templates.
- Prove local-first value before expanding cloud features.
- Prioritize reliable Events over broad AI categories.
- Keep early configuration guided and constrained.
- Add complexity only when it improves adoption, trust, or operational value.

## Phase 0: Product Definition and Validation

Goal: Validate the product specification and commercial thesis.

Outcomes:

- Specification Pack reviewed.
- Core terminology approved.
- Target first customer profile selected.
- Non-goals confirmed.
- Privacy position confirmed.
- Commercial packaging assumptions drafted.

Key validation questions:

- Which venue category has the strongest first buying pain?
- What is the minimum useful Event set?
- How much setup effort is commercially acceptable?
- What privacy promises must be made explicitly?

## Phase 1: Generic Venue Intelligence Core

Goal: Deliver the smallest useful local-first product that can configure a Venue and generate operational Events.

Product scope:

- Organization.
- Venue.
- Space.
- Video Source.
- Asset Type.
- Asset.
- Zone and polygon setup.
- Basic Sensors.
- Observations.
- State.
- Events.
- Live dashboard.
- Source health.
- Manual review.

Recommended Sensor focus:

- Presence.
- Occupancy.
- Activity.
- Inactivity.
- Source health.

Reasoning: These provide broad operational value across venue categories with manageable complexity.

## Phase 2: Sessions and Operational Review

Goal: Convert Events into meaningful activity periods and make review trustworthy.

Product scope:

- Session Types.
- Configurable start and end rules.
- Session timeline.
- Confirmation.
- Correction.
- Voiding.
- Review queue.
- Session analytics.

Reasoning: Sessions are where many customers will see business value, but they depend on trustworthy Events.

## Phase 3: Notifications and Exception Management

Goal: Help operators act at the right time.

Product scope:

- Notification rules.
- Severity.
- Cooldowns.
- Escalation.
- Acknowledgement.
- Resolution.
- Notification analytics.

Reasoning: Notifications should be added after Events and States are stable enough to avoid noise.

## Phase 4: Analytics and Multi-Venue Insight

Goal: Turn operational history into management insight.

Product scope:

- Utilization analytics.
- Occupancy analytics.
- Session analytics.
- Event trends.
- Health trends.
- Cross-venue views.
- Saved reports.
- Exportable summaries.

Reasoning: Historical analytics become valuable once enough high-quality Events and Sessions exist.

## Phase 5: Templates and Commercial Scaling

Goal: Reduce setup effort without hardcoding vertical logic.

Product scope:

- Venue templates.
- Asset Type templates.
- Sensor templates.
- Dashboard templates.
- Notification templates.
- Guided setup.
- Configuration quality scoring.

Example templates:

- Recreational venue template.
- Food service venue template.
- Warehouse template.
- Office occupancy template.

These templates should be configuration packages, not code forks.

## Phase 6: Optional Cloud and Integrations

Goal: Expand commercial value while preserving local-first operation.

Product scope:

- Remote dashboards.
- Cross-venue sync.
- Cloud metadata backup.
- Scheduled reports.
- Optional evidence sync.
- Integration events.
- Webhooks or partner connectors.

Reasoning: Cloud features should amplify operations, not become mandatory for core local value.

## Phase 7: Advanced Intelligence

Goal: Add higher-value intelligence only after core reliability is proven.

Possible scope:

- Advanced anomaly detection.
- Forecasting from historical Events.
- Automatic configuration suggestions.
- Sensor confidence optimization.
- More sophisticated flow analytics.

Explicit caution:

- Identity recognition remains out of default scope.
- Any sensitive AI category requires separate approval.

## Features to Defer

Defer until strong business demand exists:

- Full custom rule builder.
- Deep POS or ERP integration.
- Audio analytics.
- Employee identity analytics.
- Full CCTV video archive replacement.
- Custom industry modules.
- Complex simulation or prediction.

## Roadmap Risks

### Risk: Overbuilding Before First Repeatable Use Case

Mitigation: Start with a small, generic Event set and 1 to 2 strong venue categories for validation while keeping the model generic.

### Risk: Cloud Features Distract From Local Core

Mitigation: Require each cloud feature to preserve local operation and justify operating cost.

### Risk: Templates Become Hardcoding

Mitigation: Treat templates as editable configuration packages that use the same domain model.

### Risk: AI Feature Creep

Mitigation: Approve AI categories through privacy, reliability, and business-value review.
