# Strikee Vision Specification Pack

Status: Draft for product review  
Scope: Product specification only  
Technology decisions: Explicitly out of scope

## Purpose

Strikee Vision is an Operations Intelligence Platform for physical venues. It turns existing CCTV and video feeds into real-time operational insight while keeping video local by default, making cloud optional, and preserving a generic product model that can serve gaming lounges, snooker clubs, arcades, restaurants, cafes, warehouses, offices, and other physical operations.

This pack defines what the product is, how it behaves, what objects exist in the product, how users configure and operate it, and what must be true for the product to be considered acceptable.

It does not choose frameworks, cloud providers, database engines, AI vendors, programming languages, or infrastructure topology.

## Product Principles

- Local first.
- Video stays local by default.
- Cloud is optional.
- AI observes, software decides.
- Configuration over code.
- Events are immutable.
- Everything business-relevant is an Asset.
- Every business decision comes from Events.
- Privacy first.
- Low operating cost.
- Reliable over clever.

## Pack Contents

1. [Product Bible](01-product-bible.md)
2. [Product Values](02-product-values.md)
3. [Domain Model](03-domain-model.md)
4. [Functional Specification](04-functional-specification.md)
5. [User Journeys](05-user-journeys.md)
6. [Dashboard Specification](06-dashboard-specification.md)
7. [Polygon Editor Specification](07-polygon-editor-specification.md)
8. [Analytics Specification](08-analytics-specification.md)
9. [Notification Specification](09-notification-specification.md)
10. [AI Behaviour Specification](10-ai-behaviour-specification.md)
11. [Acceptance Criteria](11-acceptance-criteria.md)
12. [Product Roadmap](12-product-roadmap.md)
13. [Decision Log](13-decision-log.md)
14. [Product Architecture Diagrams](14-product-architecture-diagrams.md)
15. [Reference Venue Configuration: Snooker and Gaming](15-reference-venue-configuration-snooker-gaming.md)
16. [Venue Survey and MVP Scope](16-venue-survey-and-mvp-scope.md)
17. [Gaps and Open Questions](17-gaps-and-open-questions.md)

## Terminology Rules

- Use Venue for a real-world business location.
- Use Business Unit for a separately managed analytics and operational reporting group inside an Organization or Venue.
- Use Space for a physical subdivision of a Venue.
- Use Video Source for any camera stream, recording source, or video input.
- Use Asset for anything business-relevant that can be configured, observed, assigned, measured, or reported on.
- Use Sensor for a first-class observation object with a subject (Asset), an evidence source (Video Source), and a spatial scope (Zone); its lifecycle home is the Asset. Camera-health is a property of the Video Source, not a Sensor.
- Use Observation for raw or near-raw AI output.
- Use State for the current derived condition of an Asset, Space, or operational concept.
- Use Event for an immutable business-relevant fact derived from one or more observations or state transitions.
- Use Session for a bounded period of operational activity inferred from Events.
- Do not use Space as the only analytics boundary. Spaces describe physical layout; Business Units describe operational reporting attribution.

## Review Standard

This pack should be reviewed as a commercial product specification:

- Can a customer understand what the product does?
- Can product, design, engineering, QA, and operations build from this without guessing the intent?
- Are objects generic enough to support multiple venue categories?
- Are complexity and configuration justified by clear business value?
- Are privacy and local-first constraints preserved throughout the design?
