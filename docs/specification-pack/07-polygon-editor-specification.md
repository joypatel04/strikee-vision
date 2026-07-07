# Polygon Editor Specification

## Purpose

The Polygon Editor lets admins define the spatial regions where Strikee Vision observes operations.

It is a product-critical setup tool because the system must adapt to real-world layouts without code changes.

## Core Concepts

### Canvas

The visual workspace showing a frame or reference image from a Video Source.

### Polygon

A user-defined shape that identifies a region of interest. A polygon is purely a drawn shape that lives inside a Zone; it is geometry, not a link target. Assets and Sensors never link to a bare polygon.

### Zone

The only named, linkable spatial object. A Zone owns one or more polygons as its geometry, and multiple polygons per Zone handle L-shapes and split views. Assets and Sensors link to Zones, never to bare polygons.

### Asset Mapping

The relationship between a Zone and one or more Assets. Mapping is always Zone-based.

### Privacy Mask

A region where observation, preview, export, or evidence visibility is restricted.

## Supported Polygon Uses

- Asset boundary.
- Occupancy region.
- Queue area.
- Entry or exit threshold.
- Staff-only area.
- Obstruction region.
- Privacy mask.
- Exclusion zone.
- Calibration zone.

## Editor Modes

### Draw Mode

User creates a new polygon.

Required behavior:

- Add points.
- Close shape.
- Snap to nearby points where helpful.
- Cancel drawing.
- Name Zone after creation.

### Edit Mode

User modifies an existing polygon.

Required behavior:

- Move points.
- Add points.
- Remove points.
- Move entire polygon.
- Duplicate polygon.
- Delete polygon with confirmation.

### Mapping Mode

User links Zones to product objects. A drawn shape becomes or joins a named Zone, and the Zone is what gets linked; polygons are never linked directly.

Required behavior:

- Link Zone to Asset.
- Link Zone to Sensor.
- Mark as privacy mask.
- Mark as exclusion zone.
- Show mapping conflicts.

### Test Mode

User validates detection behavior.

Required behavior:

- Show Sensor output preview.
- Show confidence.
- Show recent Observations.
- Show whether Events would be generated.
- Warn about low visibility, overlap, or ambiguity.

## Zone and Polygon Attributes

A Zone is the named, linkable object and carries the links. A polygon is geometry owned by a Zone.

Each Zone should have:

- Name.
- Type.
- Space.
- Video Source.
- One or more polygons (its geometry).
- Linked Assets.
- Linked Sensors.
- Privacy classification.
- Active or inactive status.
- Created by.
- Created at.
- Last modified by.
- Last modified at.

Each polygon should have:

- Coordinates relative to source frame.
- Owning Zone.

## Validation Rules

The editor should warn when:

- Polygon is too small to observe reliably.
- Polygon overlaps another active polygon in a conflicting way.
- Polygon is outside usable frame area.
- Polygon covers a masked area.
- Polygon has too many points for practical maintenance.
- Polygon is not linked to any useful object.
- Linked Asset is in a different Space.
- Video Source health is poor.

Warnings should explain the business impact, not technical internals.

## Privacy Behavior

Privacy masks should be visually distinct and protected from accidental deletion.

Required behavior:

- Show privacy masks to authorized users.
- Hide or simplify masks for unauthorized users.
- Prevent Sensors from observing inside disabled privacy regions.
- Require confirmation before reducing privacy coverage.
- Log privacy mask changes.

## Versioning and Audit

Polygon changes affect future Observations and Events. Historical Events should remain linked to the configuration version that existed when they were generated.

Required behavior:

- Record configuration change Events or audit records.
- Preserve previous polygon versions for audit.
- Let reviewers understand which polygon was active at the time of an Event.

## Editor Usability Requirements

- The editor should support precise but simple shape editing.
- Users should be able to zoom and pan.
- Users should be able to rename Zones and Assets in context.
- Users should see whether a polygon is active.
- Users should be able to test before activation.
- Users should not need to understand computer vision terminology.

## Anti-Patterns

Avoid:

- Forcing every Asset to have exactly one polygon.
- Hiding overlaps until runtime.
- Allowing privacy masks to be accidentally removed.
- Using gaming-specific labels.
- Treating polygon drawing as an engineering task.

## Acceptance Notes

The Polygon Editor is acceptable when an installer can configure a Venue's operational areas, test whether useful Events will be generated, and activate the configuration without code changes.

