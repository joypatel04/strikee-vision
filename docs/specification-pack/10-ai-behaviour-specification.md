# AI Behaviour Specification

## Purpose

This document defines how AI should behave as a product capability. It does not choose models, vendors, frameworks, hardware, or implementation architecture.

## Core Principle

AI observes. Software decides.

AI should produce Observations with confidence and evidence. Product rules should convert those Observations into State, Events, Sessions, Notifications, and Analytics.

An Asset's State has three independent facets — presence (absent, present, or unknown), activity (active, inactive, or unknown), and health (ok, degraded, or offline). Each Observation should map onto the correct facet: presence and occupancy Observations feed the presence facet, activity and motion Observations feed the activity facet, and source-quality Observations feed the health facet.

## AI Responsibilities

AI may:

- Detect presence.
- Estimate occupancy.
- Detect activity or inactivity.
- Estimate counts.
- Detect motion or lack of motion.
- Detect queue-like conditions.
- Detect dwell.
- Detect entry or exit transitions.
- Detect obstruction.
- Assess source quality.
- Provide confidence scores.

AI should not directly:

- Create final business Events.
- Start or end Sessions without product rules.
- Notify users without Event or State logic.
- Identify people by default.
- Infer sensitive attributes.
- Make employment or disciplinary judgments.

## Observation Requirements

Each AI Observation should include:

- Observation type.
- Timestamp.
- Video Source.
- Sensor.
- Zone or frame region.
- Confidence.
- Evidence reference where permitted.
- Raw or normalized value.
- Quality indicators where available.

## Confidence Behavior

Confidence should be treated as evidence strength, not truth.

Product behavior:

- Below threshold: do not affect State, or mark as low confidence.
- Near threshold: may contribute to State but require smoothing.
- Above threshold: may contribute to State transition.
- Persistently low confidence: create health or configuration warning.

## Multi-Camera Fusion

When multiple cameras observe one Asset, each camera is a Sensor with a role of primary or supporting.

- The primary Sensor decides the Asset's State.
- Supporting Sensors are used for confidence, review, and fallback when the primary is degraded or offline.

Presence override: the Asset is occupied if the primary reports occupied, or if any supporting Sensor reports occupied with high confidence. This is because occlusion tends to cause false empties, and rarely false occupied.

Weighted fusion (combining observations by confidence and recency) is deferred to post-MVP.

## Smoothing and Stability

The product should avoid rapid state flapping caused by frame-level noise.

Configurable controls:

- Minimum duration before state change.
- Minimum confidence.
- Consecutive observations required.
- Cooldown after state change.
- Hysteresis between enter and exit thresholds.

Reasoning: Operators need stable operational state, not a live stream of uncertainty.

## Unknown State

AI uncertainty must be allowed to produce Unknown state.

Unknown is appropriate when:

- Video Source is offline.
- Sensor is disabled.
- Confidence is too low.
- Privacy mask prevents observation.
- View is obstructed.
- Configuration is incomplete.
- Observations are stale.

Reasoning: Unknown is more honest than false certainty.

## Evidence and Explainability

Where permitted, users should be able to see:

- Which Sensor produced the Observation.
- Which Zone was evaluated.
- What rule converted State into Event.
- Why a Session started or ended.
- What confidence was involved.
- Whether evidence is available.

The product should avoid exposing technical model internals to normal operators.

## AI Quality Feedback

The product should show setup feedback such as:

- Low light.
- Obstructed view.
- Poor angle.
- Region too small.
- Frequent occlusion.
- Unstable confidence.
- Excessive overlap.
- Source offline or degraded.

Feedback should be framed as operational setup guidance.

## Human Correction Loop

Corrections should improve trust and configuration decisions.

Permitted uses:

- Show correction rates by Sensor or Asset.
- Suggest threshold review.
- Suggest polygon adjustment.
- Flag repeated false positives.

Avoid:

- Automatically changing configuration without user approval.
- Treating correction as model training consent by default.

## Privacy Constraints

Default AI behavior should avoid:

- Face recognition.
- Person identification.
- Demographic inference.
- Emotion inference.
- Biometric tracking.
- Staff performance scoring by identity.

If any identity-based feature is considered in the future, it should require separate product approval, legal review, explicit customer opt-in, and a separate specification.

## AI Failure Modes

The product must handle:

- False positive.
- False negative.
- Low confidence.
- Stale observations.
- Camera moved.
- Lighting change.
- Occlusion.
- Network interruption.
- Sensor disabled.
- Misconfigured polygon.

For each failure mode, the product should prefer transparent degradation over silent incorrectness.

## Acceptance Notes

AI behavior is acceptable when:

- Observations are auditable.
- Low confidence does not become false certainty.
- Users can understand why Events occurred.
- The product continues to provide value without identity recognition.
- Corrections preserve history.

