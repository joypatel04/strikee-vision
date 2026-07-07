# Notification Specification

## Purpose

Notifications tell the right users when an operational Event or persistent condition requires attention.

Notifications should reduce missed issues, not create noise.

## Notification Principles

- Notifications must be tied to Events or persistent States.
- Every notification should have a clear reason.
- Every notification should have an intended recipient or role.
- Cooldowns and escalation should prevent spam.
- Acknowledgement and resolution should be auditable.

## Notification Sources

Valid sources:

- Event created.
- State remains in condition for threshold duration.
- Session remains open longer than expected.
- Queue or count exceeds threshold.
- Video Source goes offline or degraded.
- Sensor confidence drops.
- Review queue exceeds threshold.
- Manual user action.

Invalid sources:

- Raw Observation alone, unless converted into an Event or persistent condition.

Reasoning: Notifications should be based on business facts, not noisy AI output.

## Notification Rule Attributes

Each Notification Rule should define:

- Name.
- Scope.
- Trigger Event Type or State condition.
- Severity.
- Recipients or roles.
- Channel.
- Operating schedule.
- Cooldown.
- Escalation rule.
- Auto-resolve behavior.
- Active or inactive status.

## Severity Levels

Recommended severity levels:

- Info: Useful but not urgent.
- Warning: Needs attention soon.
- Critical: Needs immediate action.

Avoid too many severity levels. More levels increase configuration complexity without clear operator value.

## Notification Lifecycle

States:

- Pending.
- Delivered.
- Acknowledged.
- Resolved.
- Suppressed.
- Failed.

Required behavior:

- Creation links to triggering Event or condition.
- Delivery status is tracked.
- Acknowledgement records user and time.
- Resolution records user or auto-resolution reason.
- Suppression records rule and reason.

## Channels

Product should support channel concepts without committing this spec to specific vendors.

Possible channels:

- In-app.
- Local display.
- Email.
- SMS.
- Messaging app.
- Webhook or integration.

Early product should prioritize in-app and low-cost channels before adding expensive or complex delivery paths.

### Local-First Channel Tiers

Channels are tiered so local operation stays useful during an internet outage:

- In-app and local on-screen channels always work offline. They are rendered by the local application and are the guaranteed delivery floor.
- Network channels (email, SMS, messaging app, webhook or integration) are best-effort. When offline they are queued and auto-retried on reconnect, never silently dropped.

When a network channel cannot deliver, the attempt enters the `Failed` lifecycle state; the dashboard surfaces this as a "delivery degraded / N pending" banner rather than failing silently, and delivery status is tracked per attempt so a queued item can move from `Failed` to `Delivered` once reconnected.

Every Critical notification rule must include at least one local channel, so a critical alert can never depend solely on the internet.

## Escalation

Escalation should occur when:

- Notification is unacknowledged for configured time.
- Critical condition persists.
- Primary recipient is unavailable.

Escalation targets:

- Higher role.
- Alternate recipient.
- Venue manager.
- Organization admin.

## Suppression and Cooldown

Suppression is necessary when repeated Events occur from the same unresolved condition.

Examples:

- Camera offline notification should not send every minute.
- Queue threshold should not repeatedly alert while the same queue condition remains active.

Required behavior:

- Cooldown by rule and subject.
- Suppression reason visible.
- Suppressed notifications counted for analytics where useful.

## Notification Detail View

Should show:

- Title.
- Severity.
- Current status.
- Triggering Event.
- Subject Asset, Space, or Source.
- Created time.
- Delivered time.
- Acknowledged by.
- Resolved by.
- Evidence link where permitted.
- Recommended action text where configured.

## Anti-Patterns

Avoid:

- Alerting on every low-confidence observation.
- Sending notifications without ownership.
- Hardcoding business-specific notification types.
- Requiring cloud delivery for local operation.
- Making acknowledgement modify the original Event.

## Acceptance Notes

Notifications are acceptable when operators receive timely, explainable, low-noise messages that link back to immutable Events and can be acknowledged or resolved with an audit trail.

