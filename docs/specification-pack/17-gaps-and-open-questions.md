# Gaps and Open Questions

Status: Draft for product review
Purpose: Records gaps, contradictions, and under-specified areas found while reviewing the Strikee Vision specification pack (docs 01–16). Each item is written to be resolved one at a time, with a decision recorded inline.

This document does not change the product direction on its own. It is a working list. As each item is decided, update its **Decision** field and, where needed, amend the source document and the [Decision Log](13-decision-log.md).

**Status: all 15 items (G01–G15) are DECIDED, and the decisions have been applied back into the source documents (01–14) and the Decision Log (new decisions D014 amended, D015 accepted, D018–D027 added; open questions O001 and O005 resolved). This document remains the rationale record.**

## How to Read This

Each item has:

- **Severity**: Tier 1 (blocks implementation), Tier 2 (inconsistency or thin area), Minor (nit).
- **Where**: the documents involved.
- **Problem**: what is wrong or missing, in plain terms.
- **Why it matters**: the practical consequence if left unresolved.
- **Options**: candidate resolutions.
- **Decision**: filled in as we resolve each one. Starts as `OPEN`.

## Status Summary

| # | Title | Severity | Status |
| --- | --- | --- | --- |
| G01 | Sensor ownership is ambiguous (four possible parents) | Tier 1 | DECIDED (A) |
| G02 | Multi-camera fusion undefined; Asset Coverage not modeled | Tier 1 | DECIDED (A) |
| G03 | Single State enum cannot represent presence + activity | Tier 1 | DECIDED (A) |
| G04 | Continuous/scalar metrics do not fit Events+Sessions model | Tier 1 | DECIDED (A) |
| G05 | Session materialized vs recomputed; late/out-of-order data | Tier 1 | DECIDED (A) |
| G06 | Core Rule contract is only Proposed (D015) | Tier 1 | DECIDED (A) |
| G07 | Business Unit position in domain chain contradicts BU thesis | Tier 2 | DECIDED (A) |
| G08 | Cross-BU attribution undefined for multi-asset sessions | Tier 2 | DECIDED (A) |
| G09 | Acceptance criteria have no quantified targets | Tier 2 | DECIDED (A) |
| G10 | Cloud notification channels break local-first promise | Tier 2 | DECIDED (A) |
| G11 | Evidence references can dangle under retention | Tier 2 | DECIDED (A+B) |
| G12 | Zone vs Polygon overlap | Tier 2 | DECIDED (A) |
| G13 | "Anomaly" listed as core but treated as Phase 7 | Minor | DECIDED (A) |
| G14 | Access control thin; no Business-Unit-scoped permissions | Minor | DECIDED (A-light) |
| G15 | Nested Spaces have no depth limit or roll-up rule | Minor | DECIDED (A) |

---

## Tier 1 — Design holes that block implementation

### G01: Sensor ownership is ambiguous (four possible parents)

**Where:** README §Terminology; 03 Domain Model (Sensor entity, ERD); 11 Acceptance Criteria §Sensor; 14 Diagram 2, 7, 25.

**Problem:** A Sensor is described with four different parents across the pack: attached to an Asset, attached to a Space, scoped by a Zone, and powered by a Video Source. These are presented as alternatives, but a working sensor plausibly needs several at once: a spatial scope (Zone), an evidence source (Video Source), and a business subject (Asset).

**Why it matters:** Sensor is the most-referenced runtime entity. Its ownership determines lifecycle, cascade delete, configuration UI, and how Observations are routed to State. It cannot be built until its shape is fixed.

**Options:**

- A. Sensor is a first-class object with explicit references: one Video Source (evidence), one Zone (scope), one subject (Asset or Space). Ownership for lifecycle sits with the subject.
- B. Sensor belongs to the Asset; Zone and Video Source are references, not parents.
- C. Sensor belongs to the Video Source (evidence-first); subject and zone are references.

**Decision:** DECIDED — Option A. Sensor is a first-class object: `{ subject: Asset, source: Video Source, scope: Zone, type, thresholds, schedule }`. Lifecycle home is the **Asset** (delete/configure through the Asset). Space-level and passage/entry observation is handled by modeling those areas as Assets (e.g., "Passage Zone" Asset), so a Sensor's subject is always an Asset. Pure camera-health sensing is **not** a Sensor — it is a property of the Video Source. Amend README §Terminology, 03 Domain Model (Sensor entity + ERD), and 11 Acceptance Criteria §Sensor to match.

---

### G02: Multi-camera fusion undefined; Asset Coverage not modeled

**Where:** 03 Domain Model §Asset Coverage; 15 Reference Config §Multi-Camera; 16 MVP §Multi-Camera Asset Coverage; 10 AI Behaviour; ERDs in 03 and 14.

**Problem:** The reference and MVP docs make "one Asset, multiple cameras, one State" central (primary + supporting views). But (a) there is no `ASSET_COVERAGE` entity in either ERD, and (b) no rule defines how conflicting observations from multiple sources are combined into a single State (e.g., Camera A "occupied 0.9" vs Camera B "empty 0.4").

**Why it matters:** Multi-source fusion is the hardest real-world problem in the product and the reference venue depends on it (Tables 1 and 2 each have two cameras). Without a fusion rule, State derivation is undefined for the primary MVP assets.

**Options:**

- A. Primary/supporting model: one Video Source is authoritative for State; supporting sources are used only for confidence, review, and fallback when the primary is degraded.
- B. Weighted fusion: combine observations by confidence and recency into a single derived value, then threshold.
- C. Highest-confidence-wins per time window, with smoothing.

**Decision:** DECIDED — Option A (primary/supporting), with a presence override. Each Asset's sensors are marked **primary** or **supporting** at setup. The primary sensor decides State; supporting sensors are used for confidence, review, and fallback when the primary is degraded/offline. Refinement for presence/occupancy only: the Asset is **occupied if the primary says occupied OR any supporting sensor reports occupied with high confidence** (occlusion causes false *empties*, rarely false *occupied*). Weighted fusion (Option B) is deferred to post-MVP once real footage exists to tune it. Add an explicit **Asset Coverage** concept: an Asset has one or more (Video Source + Zone + role[primary|supporting]) sensor bindings, all feeding the Asset's single State. Add `ASSET_COVERAGE` (or equivalent sensor-role attribute) to the ERD in 03 and 14.

---

### G03: Single State enum cannot represent presence + activity

**Where:** 03 Domain Model §State Model Guidance; 16 MVP §MVP Events and §Session Rules.

**Problem:** The MVP treats "became occupied" (presence) and "activity started/stopped" (activity) as separate events, and sessions can be occupancy-based or activity-based. Presence and activity are independent axes. But an Asset carries exactly one current State, so "occupied but inactive" vs "available and idle" cannot be expressed cleanly, and the enum definitions already overlap (Idle = "not active but may not be available").

**Why it matters:** State is the backbone of dashboards, events, and sessions. If it conflates two axes, downstream events and analytics inherit the ambiguity.

**Options:**

- A. Multi-dimensional State: separate presence, activity, and health facets, each with its own value and confidence. Dashboard derives a display label from the facets.
- B. Keep one enum but define explicit compound states with precise definitions and transition rules.
- C. Two linked sensors, one composite State object that stores both axes but exposes a single primary label.

**Decision:** DECIDED — Option A. State is a small structured object with three independent **facets**, each with its own value, confidence, and effective time:

- `presence`: `absent | present | unknown`
- `activity`: `active | inactive | unknown`
- `health`: `ok | degraded | offline`

The dashboard shows **one derived label** via a fixed mapping (health wins first, so a broken camera never shows a confident business status):

- health `offline`/`degraded` → **Unknown / Degraded**
- presence `present` + activity `active` → **Active (In Use)**
- presence `present` + activity `inactive` → **Occupied – Idle**
- presence `absent` → **Available**
- otherwise → **Unknown**

Rationale: the MVP already emits presence ("became occupied") and activity ("activity started/stopped") as separate events, so the data model should carry both facets. Health is separated so it can never corrupt business status. Update 03 §State Model Guidance and 16 accordingly; the flat enum list becomes the set of derived display labels.

---

### G04: Continuous/scalar metrics do not fit the Events+Sessions model

**Where:** 13 Decision Log D014; 08 Analytics (occupancy by hour, average/peak occupancy, queue over time); 14 Diagram 17.

**Problem:** D014 and the analytics principles say metrics come from Events and Sessions, not raw video. But several required metrics are scalar time-series (average occupancy, peak occupancy, occupancy by hour, queue estimate over time). These cannot be reconstructed from discrete threshold-crossing Events or from Sessions. Diagram 17 quietly adds "State history" as a third source, but the prose does not.

**Why it matters:** Either the analytics promises are unbuildable, or a first-class scalar sampling/time-series source is needed that no document defines.

**Options:**

- A. Add a first-class time-series/metric sample stream (periodic scalar snapshots) as an explicit analytics source alongside Events and Sessions; amend D014.
- B. Narrow the analytics scope to duration/count metrics derivable from state transitions, and drop average/peak scalar metrics for now.
- C. Sample scalars into periodic "measurement Events" so they remain within the events model.

**Decision:** DECIDED — Option A. Add a third analytics source, **Metric Samples**, kept separate from Events and Sessions. Amend D014 to read "analytics aggregate **Events, Sessions, and Metric Samples**."

- **Events** = immutable business facts (few, long retention, auditable).
- **Sessions** = spans derived from Events.
- **Metric Samples** = periodic scalar snapshots (occupancy count, per-facet confidence, queue estimate, health), high-volume, **short retention with downsampling** (e.g. raw for ~7 days, then rolled up to hourly/daily aggregates).

**Zero added inference cost:** the deployment already runs local AI on each feed on a fixed **5–10s processing tick** (see deployment constraints below). Each tick already computes the facet values, so it emits **one Metric Sample per sensor per tick** as a cheap row — no extra model runs. The sampling cadence == the processing cadence. This is the source for average/peak/by-hour/over-time metrics that Events alone cannot produce.

**Deployment constraints (project-wide, apply to all items):**

- All AI inference and processing runs **locally on Windows** at the venue. No cloud inference.
- A **dashboard** is the primary surface for viewing everything (live state, events, sessions, analytics, health).
- **Performance budget is tight** — must not add per-frame cost. Processing is periodic, **every 5–10 seconds per feed**, not per-frame/real-time streaming inference.
- Analytics, state derivation, and metric sampling must all fit within this periodic, low-overhead local model.

---

### G05: Session materialized vs recomputed; late and out-of-order data

**Where:** 13 Decision Log D008; 03 Domain Model §Session; 04 Functional §Session; 05 Journey 3.

**Problem:** Sessions are "derived from Events" (D008) yet also stored objects with a mutable status and correctable start/end. It is unspecified whether a Session is recomputed from the event stream or materialized once and patched. Separately, out-of-order and late observations, and clock skew between cameras, are never addressed, though every rule assumes monotonic time.

**Why it matters:** Determines correctness when a late Observation or correction arrives after a Session closes (reopen? recompute? ignore?). This is a guaranteed source of bugs in a multi-camera streaming system.

**Options:**

- A. Materialized sessions with append-only correction events; a late event within a grace window can amend an open or recently-closed session, otherwise it creates a correction. Define the grace window.
- B. Fully recomputed sessions from the immutable event log; status is a computed view. Simpler correctness, heavier compute.
- C. Hybrid: materialize for live dashboards, recompute for analytics/reporting.

**Decision:** DECIDED — Option A. Sessions are **materialized** stored records (built from events, not recomputed per read) carrying status: detected/confirmed/corrected/voided.

- **Open rule:** session opens when presence/activity holds for a configured **minimum start duration** (per Asset Type).
- **Grace window / close rule:** session closes only after activity clears for a configured **minimum clear duration** (the grace window, e.g. 1–2 min). A straggler reading within the window keeps the session open — no reopen logic needed because it was never closed.
- **After close:** late readings do **not** resurrect a closed session. Genuine new activity starts a **new** session. If two sessions should be one, a human applies a **merge correction event** — never an automatic reopen.
- **Corrections** (fix start/end, void, merge) are always **append-only events**. Original session numbers are preserved; corrected values are shown and used by analytics.

Fits the local 5–10s tick model: the minimum-clear grace window naturally absorbs timing jitter and inter-camera clock drift; materialized reads keep the dashboard instant and cheap (no event-log replay per view). Each Asset Type must define **min start duration** and **min clear duration**. Update 03 §Session, 04 §Session, and note the two durations as required Asset Type config.

---

### G06: Core Rule contract is only Proposed (D015)

**Where:** 13 Decision Log D015 (status Proposed); 03 §Rule; 02 §Configuration Over Code.

**Problem:** The "configurable but constrained" rule engine is the only decision still in Proposed status, yet the entire "configuration over code" promise rests on it. The concrete shape of state-derivation, event, session, and notification rules is undefined.

**Why it matters:** Nothing in the pipeline can be built to a stable contract until rule shape is pinned down.

**Options:**

- A. Constrained declarative rules: a fixed catalog of parameterized rule templates (thresholds, durations, hysteresis, schedules) with no free-form logic.
- B. Small expression/DSL layer for advanced users, on top of the template catalog.
- C. Defer advanced rules; ship a fixed built-in rule set for MVP with only threshold/duration parameters exposed.

**Decision:** DECIDED — Option A. A **fixed catalog of parameterized rule templates**. Users tune numbers and choices only; no free-form rule builder. Adding a new *kind* of rule is a product/engineering action (new template), not a user action. **Flip D015 from Proposed to Accepted.** Keep Option B (small expression layer) as a documented future option, added on top only if a real customer needs it.

Every template ships with **sensible defaults** and an **ON/OFF switch**, so a venue can go live on defaults with zero tuning, disable rules it doesn't want, and adjust numbers only where reality demands it (directly mitigates the setup-complexity risk).

Initial template catalog:

- **Occupancy rule** — sensor → confidence threshold + min duration → sets `presence` facet.
- **Activity rule** — sensor → sensitivity + min duration → sets `activity` facet.
- **Session rule** — start facet + min start duration; end facet + min clear duration (grace window, per G05) → opens/closes session.
- **Threshold rule** — count/queue sensor → threshold value + direction → fires event.
- **Health rule** — video source → freshness + confidence limits → sets `health` facet.
- **Notification rule** — trigger event/state + severity + recipients + cooldown + escalation.

Each template evaluates cheaply within the 5–10s tick (reliable over clever), and every resulting event/state is explainable ("Occupancy rule on Table 1, threshold 60%, held 30s"). Update 03 §Rule and 02 §Configuration Over Code; record the flip in 13 Decision Log D015.

---

## Tier 2 — Inconsistencies and thin areas

### G07: Business Unit position in domain chain contradicts the BU thesis

**Where:** 03 Domain Model §Core Domain Chain (`Venue → Business Unit → Space → Asset`); vs 03 ERD (`SPACE }o--o{ BUSINESS_UNIT`), D016, 14 Diagram 2.

**Problem:** One textual chain places Space under Business Unit, contradicting the pack's signature idea that Space (physical) and Business Unit (analytics attribution) are orthogonal, with a Space able to support many BUs.

**Why it matters:** The contradiction undermines the clearest differentiator and will confuse implementers reading the chain literally.

**Options:**

- A. Fix the text so Space and Business Unit are parallel children of Venue; Assets carry BU attribution, Spaces optionally reference a primary BU but are many-to-many.

**Decision:** DECIDED — Option A (correctness fix). Space (physical) and Business Unit (reporting) are **parallel children of Venue**; they cross-connect through the Asset. The Asset carries both its Space (physical home) and its Business Unit (reporting attribution). A Space may optionally reference a primary BU for convenience, but real attribution lives on the Asset (this is what makes shared spaces like the passage work). Corrected chain:

```
Organization → Venue → { Space (physical), Business Unit (reporting) } → Asset → Sensor → Observation → State → Event → Session
```

Fix the textual core chain in 03 Domain Model to remove `Business Unit → Space`; it should match the ERD (`SPACE }o--o{ BUSINESS_UNIT`), D016, and 14 Diagram 2.

---

### G08: Cross-BU attribution undefined for multi-asset sessions

**Where:** 04 Functional §2A; 13 Decision Log O005; 03 §Session.

**Problem:** Events and Sessions inherit BU from participating Assets, but if a Session spans Assets from different BUs (e.g., shared zone + snooker table), which BU applies is undefined. O005 covers shared-space attribution but not the multi-asset-session case.

**Why it matters:** Analytics separation by BU is a core promise; ambiguous attribution corrupts it.

**Options:**

- A. Sessions are single-BU by construction in MVP (a session belongs to exactly one Asset/BU); shared activity is tracked as separate neutral sessions.
- B. Multi-asset sessions allowed, with an explicit primary-BU rule (e.g., the initiating asset's BU).

**Decision:** DECIDED — Option A. In MVP, **one session = exactly one Asset = one Business Unit**. No mixed-BU sessions. The passage/lobby is its own Asset in the Shared/Neutral BU, so passage dwell is its own separate session and never merges with a table/station session. Cross-BU customer journeys (e.g., "waited in passage, then played snooker") are a **future analytics/attribution feature**, not part of session identity — consistent with O005. Update 03 §Session to state sessions are single-Asset in this phase.

---

### G09: Acceptance criteria have no quantified targets

**Where:** 01 Product Bible (line ~227, "targets documented in acceptance criteria"); 11 Acceptance Criteria (all qualitative); 16 MVP §Detection Quality Targets (deferred).

**Problem:** The Bible promises real-time/accuracy targets live in the acceptance criteria, but doc 11 has no numbers (latency, accuracy %, freshness seconds). The cross-reference points at content that does not exist.

**Why it matters:** QA and engineering cannot verify "real-time" or "reliable" without numbers; the promise is untestable.

**Options:**

- A. Add provisional numeric targets to doc 11 (e.g., state freshness < N seconds, occupancy accuracy > X% under normal conditions), marked "to be validated after camera sampling."
- B. Explicitly move targets to the MVP doc and fix the Bible cross-reference.

**Decision:** DECIDED — Option A. Add provisional numeric targets to 11 Acceptance Criteria, each tagged **"provisional — validate after camera sampling."** Fix the Bible cross-reference so it points at real content. Seed targets (anchored to the 5–10s tick):

- **State freshness:** state reflects reality within **~15 s** under normal conditions (≈2× a 10s tick, tolerates one missed tick).
- **Stale → Unknown:** no fresh reading for **~30–60 s** flips state to Unknown/Degraded rather than showing stale data.
- **Occupancy accuracy:** correct occupied-vs-available on high-priority assets **≥ 90%** under normal operating conditions (adequate light, clear view).
- **Session timing:** start/end within **±1–2 min** of truth — explicitly not billing-grade, human-correctable.
- **Camera-down visibility:** offline/degraded camera surfaces on the dashboard within **~60 s**.
- **Dashboard load/refresh:** live view usable within **~2–3 s**.

All tunable after real footage.

---

### G10: Cloud notification channels break the local-first promise

**Where:** 02 §Local First; 09 Notification §Channels; 05 Journey 2 (useful during outage).

**Problem:** The product guarantees useful local operation during internet outages, but Email/SMS/messaging/webhook channels are network-dependent. Behaviour of a Critical escalation during an outage is unspecified.

**Why it matters:** A silent failure of critical alerts during an outage is an operational and trust risk.

**Options:**

- A. Local-first notification tiers: in-app/local-display always work offline; network channels are best-effort with a visible "delivery degraded" state and a queued-retry on reconnect.
- B. Require at least one local channel per critical rule.

**Decision:** DECIDED — Option A, plus the B guarantee. Tiered channels:

- **In-app / local on-screen notifications always work offline** (rendered by the local Windows app/dashboard) — the guaranteed floor.
- **Network channels (email/SMS/webhook) are best-effort:** when offline they are **queued and auto-retried on reconnect**, and the dashboard shows a visible **"delivery degraded / N pending"** banner (no silent failure). Uses the existing `Failed` notification state; add a delivery status per attempt.
- **Every Critical notification rule must include at least one local channel**, so a critical alert can never depend solely on internet.

Fits the local-Windows model (app already runs on-site). Update 09 Notification §Channels and 02 §Local First.

---

### G11: Evidence references can dangle under retention

**Where:** 04 §15 Privacy; 13 O003; 03 §Event (evidence reference).

**Problem:** Events are immutable and reference evidence, but retention deletes clips before Event metadata. The lifecycle of an Event whose evidence has expired (and what Review shows then) is unspecified.

**Why it matters:** Review and audit workflows break silently when evidence is gone.

**Options:**

- A. Evidence references carry an availability state (available/expired/masked); Review shows "evidence expired" gracefully; retention policy is surfaced at review time.
- B. Preserve a lightweight evidence artifact (thumbnail/keyframe/metadata) beyond the full clip retention window.

**Decision:** DECIDED — **A + B combined.**

- Each evidence reference carries an **availability status**: `available | expired | masked`. Review shows a graceful message (e.g. "Evidence expired on [date] per retention policy") instead of a broken link.
- On Event creation, also save **one tiny keyframe/thumbnail** (single small image, not the clip). **Full clip = short (video) retention; keyframe + availability status = long (Event) retention** alongside the Event. A single still usually answers audit questions ("was this real?") for a few KB vs MB of clip — fits local-Windows / low-cost.
- Privacy preserved: **masked zones are never snapshotted**; keyframe access is permissioned like any evidence. Update 04 §15 Privacy, 03 §Event, and 13 O003 (retention defaults).

---

### G12: Zone vs Polygon overlap

**Where:** 07 Polygon Editor (Zone = one or more polygons); 03 (Asset mapped to polygons; Zone linked to Assets); Sensors scoped to "Zone or Polygon."

**Problem:** Two overlapping spatial abstractions. Assets and Sensors link to "Zone or Polygon" interchangeably across docs, with an unclear boundary.

**Why it matters:** Ambiguity in the spatial model complicates the polygon editor, sensor scoping, and audit-of-configuration.

**Options:**

- A. Make Zone the only linkable spatial object; a Zone owns one or more polygons; Assets and Sensors link to Zones, never bare polygons.
- B. Keep both but define strict rules for when each is used.

**Decision:** DECIDED — Option A. **Zone** is the only named, linkable spatial object; it owns **one or more polygons** as its geometry. **Assets and Sensors always link to Zones, never to bare polygons.** A polygon is purely a drawn shape inside a Zone (geometry detail, not a link target). Installer model: draw shape → it becomes/joins a named Zone → link the Zone to the Asset and its sensor. Handles L-shapes and split views via multiple polygons per Zone without exposing plumbing. Update 03 (Asset/Sensor link to Zone, not polygon), 07 Polygon Editor, and the G01 sensor definition (`scope: Zone`).

---

## Minor

### G13: "Anomaly" listed as core but treated as Phase 7

**Where:** 01 Product Bible (line ~233, anomaly among prioritized observations); 04 Functional sensor list (absent); 12 Roadmap Phase 7 (advanced anomaly).

**Problem:** Inconsistent placement of anomaly detection between core and advanced scope.

**Options:** A. Remove anomaly from the core observation list in the Bible and keep it in Phase 7.

**Decision:** DECIDED — Option A. Remove "anomaly" from the core prioritized-observation list in 01 Product Bible; it stays a Phase 7 advanced feature. MVP focuses on concrete signals (occupancy, presence, activity, dwell), not fuzzy "abnormal" detection.

---

### G14: Access control thin; no Business-Unit-scoped permissions

**Where:** 05 Personas; 14 Diagram 5; 03 §User/Role/Policy.

**Problem:** Personas exist but there is no permission catalog and no spec for BU-scoped access (e.g., a user limited to the Snooker BU). Relevant for a privacy-sensitive multi-tenant product.

**Options:** A. Define a role/permission catalog and support scoping by Venue and Business Unit. B. Defer BU-scoping past MVP but note it explicitly.

**Decision:** DECIDED — Option A (light). For MVP: define a **simple role→permission table** (Admin: configure; Reviewer: review/correct; Manager: view + acknowledge + correct; Staff: view + acknowledge; Owner: view + analytics) with access scoped by **Venue**. **Business-Unit-scoped permissions are planned/post-MVP** — every Asset/Session/Event already carries BU attribution, so filtering by BU can be added later without rework. Rationale: reference venue is one owner running both business lines; separate per-BU staff access is not needed yet but the door stays open. Update 03 §User/Role/Policy and add the role table to a governance section.

---

### G15: Nested Spaces have no depth limit or roll-up rule

**Where:** 03 ERD (`SPACE ||--o{ SPACE`); 04 §3; 08 Analytics.

**Problem:** Nested Spaces are allowed but there is no depth limit or rule for analytics roll-up across nesting.

**Options:** A. Limit nesting to one level for MVP; define roll-up as sum of descendant spaces. B. Allow arbitrary depth with explicit roll-up rules.

**Decision:** DECIDED — Option A. **One level of nesting for MVP** — a Venue has flat Spaces (snooker area, passage, gaming area). Roll-up = simple sum of a Space's assets. Deeper nesting (multi-floor) is added later only if a real venue needs it. Update 04 §3 and 08 Analytics.

---

## Resolution Order

Recommended order of discussion: G01 → G02 → G03 → G04 → G05 → G06 (Tier 1 first, since they define the runtime data model), then Tier 2 and Minor. Each resolution should update this file, the relevant source doc, and the Decision Log where a new product decision is made.
